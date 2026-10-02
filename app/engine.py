"""Deterministic bill audit: predicts what the insurer will pay, line by line.

All money maths happens here in plain Python, never in the LLM, so the numbers are exact and every
cut carries the rule that caused it. static/engine.js is a line for line port for the web app;
tests/test_parity.py runs both on the same random bills and fails on any difference.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from . import rules


class Policy(BaseModel):
    insurer: str = "Unknown insurer"
    plan_name: str = "Health policy"
    sum_insured: float
    room_rent_limit_per_day: Optional[float] = None  # absolute cap in rupees
    room_rent_limit_pct_si: Optional[float] = None  # 1.0 means 1% of sum insured per day
    icu_limit_per_day: Optional[float] = None
    icu_limit_pct_si: Optional[float] = None
    copay_pct: float = 0.0
    consumables_cover: bool = False  # the consumables add on pays List I items
    ambulance_cover: bool = False  # most policies pay road ambulance up to a limit
    sub_limits: dict = Field(default_factory=dict)  # {"cataract": 40000}

    def room_limit(self):
        limits = []
        if self.room_rent_limit_per_day:
            limits.append(self.room_rent_limit_per_day)
        if self.room_rent_limit_pct_si:
            limits.append(self.sum_insured * self.room_rent_limit_pct_si / 100)
        return min(limits) if limits else None

    def icu_limit(self):
        limits = []
        if self.icu_limit_per_day:
            limits.append(self.icu_limit_per_day)
        if self.icu_limit_pct_si:
            limits.append(self.sum_insured * self.icu_limit_pct_si / 100)
        return min(limits) if limits else None


class BillItem(BaseModel):
    description: str
    amount: float
    category: Optional[str] = None
    days: Optional[int] = None  # for room and ICU lines


class Bill(BaseModel):
    hospital: str = "Hospital"
    treatment: str = ""  # matched against policy treatment caps, for example "cataract"
    differential_billing: bool = True  # does the hospital charge more for costlier rooms?
    items: List[BillItem]


class LineResult(BaseModel):
    description: str
    category: str
    billed: float
    payable: float
    cut: float
    status: str  # cut, protected, check, ok
    codes: List[str]  # reason codes, rendered in any language by static/i18n.js
    rule_codes: List[str]
    reasons: List[str]  # the same reasons in plain English
    rules: List[str]
    action: Optional[str] = None
    action_code: Optional[str] = None


class AuditResult(BaseModel):
    lines: List[LineResult]
    total_billed: float
    payable_before_copay: float
    copay: float
    sub_limit_cut: float
    insurer_pays: float
    you_pay: float
    room_ratio: Optional[float]
    summary: List[str]
    summary_codes: List[str]
    challengeable: float


WHERE = {"room": "room rent", "procedure": "the procedure charge", "treatment": "the treatment cost"}


def _r(x):
    return round(x + 1e-9, 2)


def _rs(x):
    return f"Rs {x:,.0f}"


def audit(policy: Policy, bill: Bill) -> AuditResult:
    room_limit = policy.room_limit()
    icu_limit = policy.icu_limit()

    cats = []
    for it in bill.items:
        cat = it.category or rules.guess_category(it.description)
        cats.append(cat if cat in rules.CATEGORIES else "other")
    has_nursing = "nursing" in cats

    # The room ratio drives proportionate deduction, so work it out first.
    ratio = None
    for it, cat in zip(bill.items, cats):
        if cat == "room" and room_limit:
            per_day = it.amount / (it.days or 1)
            if per_day > room_limit:
                r = room_limit / per_day
                ratio = r if ratio is None else min(ratio, r)
    apply_ratio = ratio is not None and bill.differential_billing

    lines: List[LineResult] = []
    for it, cat in zip(bill.items, cats):
        billed = float(it.amount)
        payable = billed
        codes, rule_codes, reasons = [], [], []
        action = action_code = None
        status = "ok"
        hit = rules.match(it.description) if cat not in ("room", "icu") else None
        kind = hit[0]["kind"] if hit else None
        term = hit[1] if hit else ""

        if kind == "not_payable":
            rule_codes.append(hit[0]["rule"])
            if policy.consumables_cover:
                codes.append("LIST_I_ADDON")
                reasons.append(f"'{term}' is on IRDAI's List I, but your consumables add on covers it.")
            else:
                payable = 0.0
                codes.append("LIST_I_NOT_PAID")
                reasons.append(f"Insurers don't pay for '{term}'. It is on IRDAI's List I.")
                action_code = "ACT_LIST_I"
                action = "Ask the billing desk to show where this was used. If it wasn't used, ask them to remove it."
        elif kind == "not_payable_if_nursing" and has_nursing:
            payable = 0.0
            rule_codes.append(hit[0]["rule"])
            codes.append("SERVICE_CHARGE")
            reasons.append("Service charges aren't paid when nursing is already charged. IRDAI List I.")
            action_code = "ACT_LIST_I"
            action = "Ask the billing desk to show where this was used. If it wasn't used, ask them to remove it."
        elif kind == "ambulance":
            rule_codes.append(hit[0]["rule"])
            if policy.ambulance_cover:
                codes.append("AMBULANCE_COVERED")
                reasons.append("Paid under your policy's ambulance cover, up to its limit.")
                status = "check"
            else:
                payable = 0.0
                codes.append("AMBULANCE_CHECK")
                reasons.append("Ambulance is paid only if your policy has ambulance cover. Most do, up to a limit.")
                action_code = "ACT_AMBULANCE"
                action = "Check your policy for ambulance cover and its limit."
        elif kind == "check":
            rule_codes.append(hit[0]["rule"])
            codes.append("TOILETRY_CHECK")
            reasons.append("Creams, powders and lotions are paid only when a doctor prescribed them as medicine.")
            action_code = "ACT_TOILETRY"
            action = "If the doctor prescribed it, keep the prescription with your claim."
            status = "check"
        elif kind == "subsumed":
            payable = 0.0
            where = hit[0]["where"]
            rule_codes.append(hit[0]["rule"])
            codes.append("SUBSUMED_" + where.upper())
            reasons.append(f"'{term}' is already part of {WHERE[where]} under IRDAI's rules, so it can't be billed again.")
            action_code = "ACT_SUBSUMED_" + where.upper()
            action = f"Ask the billing desk to remove this line. It is already part of {WHERE[where]}."
        elif cat == "room" and room_limit:
            days = it.days or 1
            allowed = room_limit * days
            if billed > allowed:
                payable = allowed
                codes.append("ROOM_OVER")
                rule_codes.append("R_POLICY_ROOM")
                reasons.append(f"This room costs {_rs(billed / days)} a day. Your policy pays up to {_rs(room_limit)} a day.")
                action_code = "ACT_ROOM"
                action = "A room within your limit also keeps doctor and surgery fees fully covered."
        elif cat == "icu":
            if icu_limit:
                days = it.days or 1
                allowed = icu_limit * days
                if billed > allowed:
                    payable = allowed
                    codes.append("ICU_OVER")
                    rule_codes.append("R_POLICY_ICU")
                    reasons.append(f"ICU costs {_rs(billed / days)} a day. Your policy pays up to {_rs(icu_limit)} a day.")
            if ratio is not None:
                codes.append("ICU_NO_PD")
                rule_codes.append("R_PD")
                reasons.append("ICU charges are never cut because of the room you chose.")
                status = "protected"

        pd_eligible = hit is None and cat in rules.ASSOCIATED_EXPENSES
        if apply_ratio and pd_eligible and payable > 0:
            payable = payable * ratio
            codes.append("PD_APPLIED")
            rule_codes.append("R_POLICY_PD")
            reasons.append(f"Your room is above the limit, so only {ratio * 100:.1f}% of this charge is paid.")
            if not action_code:
                action_code = "ACT_PD"
                action = "This cut happens only because of the room choice."
        elif ratio is not None and hit is None and cat in rules.NO_PROPORTIONATE and cat != "icu" and payable > 0:
            codes.append("PD_PROTECTED")
            rule_codes.append("R_PD")
            reasons.append("Protected. IRDAI doesn't allow a room cut on medicines, consumables, implants or tests.")
            action_code = "ACT_PROTECTED"
            action = "If the insurer cuts this line because of the room, challenge it. IRDAI doesn't allow that."
            status = "protected"

        cut = billed - payable
        if cut > 0.004:
            status = "cut"
        lines.append(LineResult(
            description=it.description, category=cat, billed=_r(billed), payable=_r(payable),
            cut=_r(cut), status=status, codes=codes, rule_codes=rule_codes, reasons=reasons,
            rules=[rules.CITES[c] for c in rule_codes], action=action, action_code=action_code,
        ))

    total = sum(l.billed for l in lines)
    payable_total = sum(l.payable for l in lines)

    summary, summary_codes = [], []
    if ratio is not None and not bill.differential_billing:
        summary_codes.append("SUM_NO_DIFF")
        summary.append("Your room is above the limit, but this hospital charges the same for every room. IRDAI says "
                       "no room cut is allowed then. Challenge it if the insurer applies one.")

    sub_limit_cut = 0.0
    treatment = bill.treatment.lower().strip()
    for name, cap in policy.sub_limits.items():
        if treatment and name.lower() in treatment and payable_total > cap:
            sub_limit_cut = payable_total - cap
            summary_codes.append("SUM_SUBLIMIT")
            summary.append(f"Your policy caps {name} at {_rs(cap)}, so {_rs(sub_limit_cut)} more is cut.")
            payable_total = cap

    if payable_total > policy.sum_insured:
        summary_codes.append("SUM_SI")
        summary.append(f"The claim is above your sum insured of {_rs(policy.sum_insured)}.")
        payable_total = policy.sum_insured

    copay = payable_total * policy.copay_pct / 100
    insurer_pays = payable_total - copay
    if copay:
        summary_codes.append("SUM_COPAY")
        summary.append(f"Your policy has a {policy.copay_pct:g}% copay, so you pay {_rs(copay)} of the approved amount.")

    challengeable = sum(l.cut for l in lines if l.action_code and l.action_code.startswith("ACT_SUBSUMED"))
    if challengeable:
        summary_codes.append("SUM_REMOVE")
        summary.append(f"{_rs(challengeable)} is billed for items that are already part of other charges. "
                       "Ask the billing desk to remove them before you pay.")
    if ratio is not None and bill.differential_billing:
        summary_codes.append("SUM_PD")
        summary.append(f"Your room is above the limit, so doctor, nursing and surgery charges are paid at {ratio * 100:.1f}%.")

    return AuditResult(
        lines=lines, total_billed=_r(total), payable_before_copay=_r(payable_total), copay=_r(copay),
        sub_limit_cut=_r(sub_limit_cut), insurer_pays=_r(insurer_pays), you_pay=_r(total - insurer_pays),
        room_ratio=round(ratio, 4) if ratio is not None else None, summary=summary,
        summary_codes=summary_codes, challengeable=_r(challengeable),
    )


def room_options(policy: Policy, items: List[BillItem], rents: List[float], days: int = 3,
                 differential_billing: bool = True, treatment: str = ""):
    """What the family pays for the same treatment in each room. items exclude the room itself."""
    out = []
    for rent in rents:
        room = BillItem(description="Room rent", category="room", amount=rent * days, days=days)
        r = audit(policy, Bill(treatment=treatment, differential_billing=differential_billing,
                               items=[room, *items]))
        out.append({"rent": rent, "days": days, "you_pay": r.you_pay, "insurer_pays": r.insurer_pays,
                    "total_billed": r.total_billed, "room_ratio": r.room_ratio})
    return out
