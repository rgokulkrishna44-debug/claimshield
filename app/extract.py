"""Reading documents: policy PDFs, hospital bills, rejection letters.

Each function tries Claude first and falls back to plain text parsing, so it never breaks at the
counter. Before anything goes to the AI, text is masked (app/privacy.py): a PDF with a text layer
is sent as masked text, not as the file. Only photos and scanned PDFs go as images.
"""

import io
import re

from pypdf import PdfReader

from . import llm, privacy, rules
from .engine import Bill, BillItem, Policy

NUM_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _obj(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


POLICY_SCHEMA = _obj({
    "insurer": {"type": "string"},
    "plan_name": {"type": "string"},
    "sum_insured": {"type": "number"},
    "room_rent_limit_per_day": NUM_OR_NULL,
    "room_rent_limit_pct_si": NUM_OR_NULL,
    "icu_limit_per_day": NUM_OR_NULL,
    "icu_limit_pct_si": NUM_OR_NULL,
    "copay_pct": {"type": "number"},
    "consumables_cover": {"type": "boolean"},
    "sub_limits": {"type": "array", "items": _obj({"name": {"type": "string"}, "amount": {"type": "number"}})},
    "clauses": {"type": "array", "items": _obj({
        "topic": {"type": "string"},
        "quote": {"type": "string"},
        "plain_english": {"type": "string"},
    })},
})

BILL_SCHEMA = _obj({
    "hospital": {"type": "string"},
    "treatment": {"type": "string"},
    "items": {"type": "array", "items": _obj({
        "description": {"type": "string"},
        "amount": {"type": "number"},
        "category": {"type": "string", "enum": rules.CATEGORIES},
        "days": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    })},
})

REJECTION_SCHEMA = _obj({
    "insurer_reason": {"type": "string"},
    "reason_type": {"type": "string", "enum": [
        "pre_existing_disease", "waiting_period", "non_disclosure", "not_medically_necessary",
        "opd_or_daycare_dispute", "documents_missing", "exclusion", "room_rent_or_deduction", "other",
    ]},
    "challengeable": {"type": "boolean"},
    "strength": {"type": "string", "enum": ["strong", "medium", "weak"]},
    "grounds": {"type": "array", "items": {"type": "string"}},
    "policy_clauses_cited": {"type": "array", "items": {"type": "string"}},
    "documents_to_attach": {"type": "array", "items": {"type": "string"}},
})


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(f"[Page {i + 1}]\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages))


def _content_for(data: bytes, mime: str, text_hint: str):
    if mime in ("text/plain", "text/csv"):
        text = data.decode("utf-8", "ignore")
    elif mime == "application/pdf":
        text = pdf_text(data)
        if len(text.strip()) < 200:  # scanned PDF, no text layer: the model has to see the pages
            return [llm.file_block(data, mime), {"type": "text", "text": text_hint}]
    else:
        return [llm.file_block(data, mime), {"type": "text", "text": text_hint}]
    return [{"type": "text", "text": privacy.mask_text(text)}, {"type": "text", "text": text_hint}]


# ---------- Policy ----------

POLICY_SYSTEM = (
    "You read Indian health insurance policy documents (IRDAI regulated) and extract the terms that "
    "decide how much of a hospital bill gets paid. Use exact numbers from the document. If a limit "
    "is not in the document, return null for it. Do not guess. For clauses, quote the policy's own "
    "words for: room rent, ICU, co-pay, sub-limits, waiting periods, pre-existing diseases, "
    "consumables, exclusions, and proportionate deduction."
)


def extract_policy(data: bytes, mime: str):
    """Returns (Policy, clauses, full_text, used_ai)."""
    text = pdf_text(data) if mime == "application/pdf" else data.decode("utf-8", "ignore")
    try:
        out = llm.ask_json(POLICY_SYSTEM, _content_for(data, mime, "Extract this policy's terms."), POLICY_SCHEMA)
        subs = {s["name"]: s["amount"] for s in out.pop("sub_limits", [])}
        clauses = out.pop("clauses", [])
        return Policy(**out, sub_limits=subs), clauses, text, True
    except (llm.LLMUnavailable, ValueError):
        return _policy_from_text(text), [], text, False


def _money(s):
    return float(s.replace(",", ""))


def _policy_from_text(text: str) -> Policy:
    t = text.lower()
    si = re.search(r"sum insured[^0-9]{0,40}([\d,]{5,})", t)
    room_pct = re.search(r"room rent[^%]{0,80}?(\d+(?:\.\d+)?)\s*%", t)
    room_abs = re.search(r"room rent[^0-9]{0,60}rs\.?\s*([\d,]{3,})", t)
    icu_pct = re.search(r"icu[^%]{0,80}?(\d+(?:\.\d+)?)\s*%", t)
    copay = re.search(r"co-?pay(?:ment)?[^%]{0,60}?(\d+(?:\.\d+)?)\s*%", t)
    return Policy(
        insurer="From uploaded policy",
        sum_insured=_money(si.group(1)) if si else 500000,
        room_rent_limit_pct_si=float(room_pct.group(1)) if room_pct else None,
        room_rent_limit_per_day=_money(room_abs.group(1)) if room_abs and not room_pct else None,
        icu_limit_pct_si=float(icu_pct.group(1)) if icu_pct else None,
        copay_pct=float(copay.group(1)) if copay else 0.0,
        consumables_cover="consumable" in t and "cover" in t and "not covered" not in t,
    )


# ---------- Bill ----------

BILL_SYSTEM = (
    "You read Indian hospital bills and list every charge line exactly as billed. Keep the "
    "hospital's wording in 'description'. Amount is the final line amount in rupees. For room and "
    "ICU lines, set days to the number of days billed. Categories: room, icu, doctor (consultations, "
    "visits), nursing, procedure (surgeon, OT, anaesthesia, packages), pharmacy (medicines, "
    "injections), consumables (gloves, syringes, dressings and other disposables), implants, "
    "diagnostics (lab, imaging), other. Do not add totals, taxes or discounts as items."
)


def extract_bill(data: bytes, mime: str):
    """Returns (Bill, used_ai)."""
    try:
        out = llm.ask_json(BILL_SYSTEM, _content_for(data, mime, "List every charge on this bill."), BILL_SCHEMA)
        return Bill(**out), True
    except (llm.LLMUnavailable, ValueError):
        text = pdf_text(data) if mime == "application/pdf" else data.decode("utf-8", "ignore")
        return bill_from_text(text), False


LINE_RX = re.compile(r"^\s*(.+?)[\s:|,]+(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:/-)?\s*$", re.I)
DAYS_RX = re.compile(r"(\d+)\s*(?:days?|nights?)\b", re.I)
SKIP_RX = re.compile(r"\b(total|sub ?total|grand total|discount|gst|cgst|sgst|tax|advance|deposit|balance|net payable|"
                     r"amount payable|amount due|bill no|bill date|uhid|ip no|mrn|reg no|page)\b", re.I)


def bill_from_text(text: str) -> Bill:
    """Same rules as static/read.js parseBill, so the phone and the server read a bill alike."""
    items = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line or SKIP_RX.search(line):
            continue
        m = LINE_RX.match(line)
        if not m:
            continue
        desc = re.sub(r"(\s+[\d,.]+)+$", "", m.group(1))
        desc = re.sub(r"^\d+[.)]\s*", "", desc).strip()
        amt = _money(m.group(2))
        if amt <= 0 or len(desc) < 3 or not re.search(r"[a-z]", desc, re.I):
            continue
        d = DAYS_RX.search(desc)
        items.append(BillItem(description=desc, amount=amt, days=int(d.group(1)) if d else None))
    return Bill(items=items)


# ---------- Q&A over the policy ----------

QA_SYSTEM = (
    "You explain an Indian health insurance policy to an ordinary family. Answer only from the "
    "policy text given. Always quote the exact policy sentence you relied on, in quotes, with its "
    "page number if shown. If the policy does not say, reply that the policy does not mention it "
    "and suggest asking the insurer in writing. Use short, simple sentences. Never invent rules."
)


def ask_policy(question: str, policy_text: str, lang_name: str = "English"):
    try:
        prompt = (f"<policy>\n{policy_text[:400000]}\n</policy>\n\nQuestion: {question}\n\n"
                  f"Answer in {lang_name}. Keep the quoted policy sentence in its original English.")
        return llm.ask_text(QA_SYSTEM, [{"type": "text", "text": prompt}], effort="low"), True
    except llm.LLMUnavailable:
        return _keyword_answer(question, policy_text), False


def _keyword_answer(question, text):
    words = {w for w in re.findall(r"[a-z]{4,}", question.lower())} - {"what", "does", "will", "covered", "cover", "policy", "much", "have", "with"}
    sentences = re.split(r"(?<=[.;])\s+", text)
    scored = sorted(((sum(w in s.lower() for w in words), s) for s in sentences), reverse=True)
    best = [s.strip() for score, s in scored[:3] if score > 0]
    if not best:
        return "I could not find this in the policy text. Ask the insurer in writing so you have a record."
    return "These lines in your policy look relevant:\n\n" + "\n\n".join(f'"{b}"' for b in best)


# ---------- Rejection letters ----------

REJECTION_SYSTEM = (
    "You help Indian policyholders check whether a health insurance claim rejection or deduction is "
    "fair. Compare the insurer's letter with the policy text and IRDAI rules you are sure of, "
    "including: the IRDAI Health Insurance Master Circular (29 May 2024) which requires a claim "
    "review committee to approve every rejection and a clear written reason; the moratorium rule "
    "(after 60 continuous months of cover, a claim cannot be contested for non-disclosure except "
    "for proven fraud); pre-existing disease waiting periods capped at 36 months; and IRDAI's ban on "
    "proportionate deduction for pharmacy, consumables, implants, diagnostics and ICU. Be honest: if "
    "the rejection looks valid, say challengeable=false and strength=weak. Only cite policy clauses "
    "that appear in the policy text."
)


def analyze_rejection(letter: bytes, letter_mime: str, policy_text: str, years_insured: float = 0):
    hint = (f"Policy text:\n<policy>\n{policy_text[:300000]}\n</policy>\n\n"
            f"The family has been continuously insured for {years_insured} years. "
            "Analyse the attached rejection letter.")
    try:
        content = _content_for(letter, letter_mime, hint)
        return llm.ask_json(REJECTION_SYSTEM, content, REJECTION_SCHEMA), True
    except (llm.LLMUnavailable, ValueError):
        text = pdf_text(letter) if letter_mime == "application/pdf" else letter.decode("utf-8", "ignore")
        return _rejection_heuristic(text, years_insured), False


GROUNDS = {
    "G_MORATORIUM": "You have been insured for more than 5 years without a break. Under IRDAI's moratorium rule, the insurer can't reject a claim for something not disclosed unless it proves fraud.",
    "G_ND_ASK": "Ask the insurer to show exactly which proposal form question was answered wrongly, and the medical proof it relies on.",
    "G_PED_CAP": "IRDAI caps the waiting period for illnesses you had before the policy at 36 months. If you are past that, this reason no longer applies.",
    "G_PED_PROOF": "Ask for the medical proof that the illness existed before the policy started.",
    "G_WAITING_PORT": "Check the policy start date and any credit from an earlier policy you ported. Waiting periods count from your first policy if you ported.",
    "G_DOCTOR": "Attach your treating doctor's letter explaining why admission was needed. The Ombudsman gives weight to the treating doctor.",
    "G_DAYCARE": "Day care treatments don't need 24 hours in hospital. Check if your treatment is listed as day care in your policy.",
    "G_DOCS": "IRDAI's 2024 rules say a claim shouldn't be rejected only because a document is missing. Send it and ask them to reopen the claim.",
    "G_LATE": "IRDAI's 2024 rules say a claim shouldn't be rejected only because it was reported late.",
    "G_PD": "IRDAI doesn't allow a room cut on medicines, consumables, implants, tests or ICU, and allows none at all if the hospital charges the same for every room.",
    "G_CRC": "Every rejection needs approval from the insurer's Claims Review Committee and must quote the exact policy clause. Ask for both in writing.",
}


def _has(t, words):
    return any(w in t for w in words)


def _rejection_heuristic(text, years):
    """Same rules, same order, same wording as static/reject.js."""
    t = text.lower()
    years = float(years or 0)
    m = re.search(r"reason\s*[:\-]\s*([\s\S]+?)(?:\n\s*\n|$)", text, re.I)
    reason = " ".join((m.group(1) if m else text).split())[:400]
    codes, strength, kind = [], "medium", "other"
    mentions_ped = _has(t, ["pre-existing", "pre existing", "preexisting"]) or re.search(r"\bped\b", t)
    if _has(t, ["non-disclosure", "non disclosure", "nondisclosure", "suppression", "not disclosed", "concealment", "misrepresentation"]):
        kind = "non_disclosure"
        if years >= 5:
            strength = "strong"
            codes.append("G_MORATORIUM")
        else:
            codes.append("G_ND_ASK")
        if mentions_ped and years >= 3:
            codes.append("G_PED_CAP")
    elif mentions_ped:
        kind = "pre_existing_disease"
        if years >= 3:
            strength = "strong"
        codes += ["G_PED_CAP", "G_PED_PROOF"]
    elif "waiting period" in t:
        kind = "waiting_period"
        codes.append("G_WAITING_PORT")
    elif _has(t, ["24 hours", "less than 24", "day care", "daycare"]):
        kind = "day_care"
        codes.append("G_DAYCARE")
    elif _has(t, ["not medically necessary", "could have been treated", "opd", "outpatient", "out patient", "no active treatment"]):
        kind = "not_medically_necessary"
        codes.append("G_DOCTOR")
    elif _has(t, ["document", "papers", "not submitted"]):
        kind, strength = "documents_missing", "strong"
        codes.append("G_DOCS")
    elif _has(t, ["intimation", "intimated", "informed late", "late notice"]):
        kind, strength = "late_intimation", "strong"
        codes.append("G_LATE")
    elif _has(t, ["room rent", "proportionate", "deduction"]):
        kind = "room_rent_or_deduction"
        codes.append("G_PD")
    codes.append("G_CRC")
    return {"insurer_reason": reason, "reason_type": kind, "challengeable": True, "strength": strength,
            "grounds": [GROUNDS[c] for c in codes], "ground_codes": codes, "policy_clauses_cited": [],
            "documents_to_attach": ["The insurer's rejection letter", "Policy schedule", "Discharge summary",
                                    "Final hospital bill and payment receipts"]}
