"""Deterministic bill audit: predicts what the insurer will pay, line by line.

All money maths happens here in plain Python, never in the LLM, so the numbers are exact and
every deduction carries the rule that caused it.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from . import rules


class Policy(BaseModel):
    insurer: str = "Unknown insurer"
    plan_name: str = "Health policy"
    sum_insured: float
    room_rent_limit_per_day: Optional[float] = None  # absolute cap in rupees
    room_rent_limit_pct_si: Optional[float] = None  # e.g. 1.0 means 1% of sum insured per day
    icu_limit_per_day: Optional[float] = None
    icu_limit_pct_si: Optional[float] = None
    copay_pct: float = 0.0
    consumables_cover: bool = False  # "consumables" add-on pays List I items
    sub_limits: dict = Field(default_factory=dict)  # e.g. {"cataract": 40000}

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
    days: Optional[int] = None  # for room / ICU lines


class Bill(BaseModel):
    hospital: str = "Hospital"
    treatment: str = ""  # e.g. "cataract", matched against policy sub-limits
    differential_billing: bool = True  # does the hospital charge more for costlier rooms?
    items: List[BillItem]


class LineResult(BaseModel):
    description: str
    category: str
    billed: float
    payable: float
    cut: float
    reasons: List[str]
    rules: List[str]
    action: Optional[str] = None  # what the family can do about this cut


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
    challengeable: float


def _r(x):
    return round(x + 1e-9, 2)


def audit(policy: Policy, bill: Bill) -> AuditResult:
    lines: List[LineResult] = []
    room_limit = policy.room_limit()
    icu_limit = policy.icu_limit()

    # Work out the room-rent ratio first, it drives proportionate deduction.
    ratio = None
    for it in bill.items:
        cat = it.category or rules.guess_category(it.description)
        if cat == "room" and room_limit:
            days = it.days or 1
            per_day = it.amount / days
            if per_day > room_limit:
                r = room_limit / per_day
                ratio = r if ratio is None else min(ratio, r)
    apply_ratio = ratio is not None and bill.differential_billing

    for it in bill.items:
        cat = it.category or rules.guess_category(it.description)
        if cat not in rules.CATEGORIES:
            cat = "other"
        billed = float(it.amount)
        payable = billed
        reasons, cites = [], []
        action = None

        hit = rules.match_irdai_list(it.description)
        if hit and cat not in ("room", "icu"):
            list_id, kw, cite = hit
            if list_id == "list_i":
                if policy.consumables_cover:
                    reasons.append("On IRDAI non-payable list, but your consumables add-on covers it.")
                else:
                    payable = 0.0
                    reasons.append(f"'{kw}' is on IRDAI's list of items insurers do not pay for.")
                    cites.append(cite)
                    action = "Not payable by insurance. Check you actually used it. If not, ask the hospital to drop it."
            else:
                payable = 0.0
                where = {"list_ii": "room rent", "list_iii": "the procedure charge",
                         "list_iv": "the treatment cost"}[list_id]
                reasons.append(f"'{kw}' should already be included in {where}, so the insurer will not pay it separately.")
                cites.append(cite)
                action = f"Ask the hospital to remove this line. IRDAI treats it as part of {where}, so you should not pay it twice."

        elif cat == "room" and room_limit:
            days = it.days or 1
            allowed = room_limit * days
            if billed > allowed:
                payable = allowed
                reasons.append(f"Room costs Rs {billed / days:,.0f}/day but your limit is Rs {room_limit:,.0f}/day for {days} day(s).")
                cites.append("Your policy's room rent limit")
                action = "Next time, choose a room within your limit. This cut also shrinks other charges (see proportionate deduction)."

        elif cat == "icu" and icu_limit:
            days = it.days or 1
            allowed = icu_limit * days
            if billed > allowed:
                payable = allowed
                reasons.append(f"ICU costs Rs {billed / days:,.0f}/day but your ICU limit is Rs {icu_limit:,.0f}/day.")
                cites.append("Your policy's ICU limit")
            reasons.append("No proportionate deduction on ICU charges.")
            cites.append(rules.CITE_PROPORTIONATE)

        if apply_ratio and cat in rules.ASSOCIATED_EXPENSES and payable > 0:
            new = payable * ratio
            reasons.append(f"Proportionate deduction: you took a costlier room, so only {ratio * 100:.1f}% of this charge is paid.")
            cites.append("Your policy's proportionate deduction clause")
            payable = new
            action = action or "This cut happens only because of the room choice."
        elif ratio is not None and cat in rules.NO_PROPORTIONATE and cat != "icu" and payable > 0:
            reasons.append("Protected: IRDAI does not allow proportionate deduction on this category.")
            cites.append(rules.CITE_PROPORTIONATE)
            action = "If the insurer cuts this line because of room rent, challenge it. IRDAI does not allow it."

        lines.append(LineResult(
            description=it.description, category=cat, billed=_r(billed), payable=_r(payable),
            cut=_r(billed - payable), reasons=reasons, rules=cites, action=action,
        ))

    total = sum(l.billed for l in lines)
    payable_total = sum(l.payable for l in lines)

    summary = []
    if ratio is not None and not bill.differential_billing:
        summary.append("Room is above your limit, but this hospital does not charge differently by room "
                       "type, so IRDAI rules say proportionate deduction must NOT be applied. Challenge it if the insurer does.")

    sub_limit_cut = 0.0
    treatment = bill.treatment.lower().strip()
    for name, cap in policy.sub_limits.items():
        if treatment and name.lower() in treatment and payable_total > cap:
            sub_limit_cut = payable_total - cap
            summary.append(f"Your policy caps {name} at Rs {cap:,.0f}, so Rs {sub_limit_cut:,.0f} more is cut.")
            payable_total = cap

    if payable_total > policy.sum_insured:
        summary.append(f"Claim is above your sum insured of Rs {policy.sum_insured:,.0f}.")
        payable_total = policy.sum_insured

    copay = payable_total * policy.copay_pct / 100
    insurer_pays = payable_total - copay
    if copay:
        summary.append(f"Your policy has {policy.copay_pct:g}% co-pay, so you pay Rs {copay:,.0f} of the approved amount.")

    challengeable = sum(l.cut for l in lines if l.action and "remove" in l.action.lower())
    if challengeable:
        summary.append(f"Rs {challengeable:,.0f} is billed for items that should be removed or included elsewhere. Ask the hospital billing desk before you pay.")
    if ratio is not None and bill.differential_billing:
        summary.append(f"Room rent above limit triggered proportionate deduction: associated charges are paid at {ratio * 100:.1f}%.")

    return AuditResult(
        lines=lines, total_billed=_r(total), payable_before_copay=_r(payable_total), copay=_r(copay),
        sub_limit_cut=_r(sub_limit_cut), insurer_pays=_r(insurer_pays), you_pay=_r(total - insurer_pays),
        room_ratio=round(ratio, 4) if ratio is not None else None, summary=summary,
        challengeable=_r(challengeable),
    )
