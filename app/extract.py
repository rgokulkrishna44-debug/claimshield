"""Reading documents: policy PDFs, hospital bills, rejection letters.

Each function tries Claude first and falls back to plain text parsing, so the demo never breaks.
"""

import io
import re

from pypdf import PdfReader

from . import llm, rules
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
        return [{"type": "text", "text": data.decode("utf-8", "ignore")}, {"type": "text", "text": text_hint}]
    return [llm.file_block(data, mime), {"type": "text", "text": text_hint}]


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


LINE_RX = re.compile(r"^\s*(.+?)[\s:|,-]+(?:rs\.?|₹|inr)?\s*([\d,]+(?:\.\d{1,2})?)\s*$", re.I)
DAYS_RX = re.compile(r"(\d+)\s*(?:days?|nights?)", re.I)
SKIP_RX = re.compile(r"\b(total|sub ?total|grand total|discount|gst|tax|advance|balance|net payable|bill no|uhid|ip no)\b", re.I)


def bill_from_text(text: str) -> Bill:
    items = []
    for line in text.splitlines():
        m = LINE_RX.match(line)
        if not m or SKIP_RX.search(line):
            continue
        desc, amt = m.group(1).strip(), _money(m.group(2))
        if amt <= 0 or len(desc) < 3:
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


def _rejection_heuristic(text, years):
    t = text.lower()
    m = re.search(r"reason\s*[:\-]\s*(.+?)(?:\n\s*\n|$)", text, re.I | re.S)
    reason = " ".join((m.group(1) if m else text).split())[:400]
    out = {"insurer_reason": reason, "reason_type": "other", "challengeable": True,
           "strength": "medium", "grounds": [], "policy_clauses_cited": [],
           "documents_to_attach": ["Rejection letter", "Policy schedule", "Discharge summary", "Final hospital bill"]}
    if "non-disclosure" in t or "non disclosure" in t or "suppression" in t:
        out["reason_type"] = "non_disclosure"
        if years >= 5:
            out.update(strength="strong", grounds=["You have more than 60 months of continuous cover. Under IRDAI's moratorium rule, the insurer cannot reject for non-disclosure unless it proves fraud."])
        else:
            out["grounds"] = ["Ask the insurer to show which question in the proposal form was answered wrongly, and the medical evidence it relies on."]
    elif "pre-existing" in t or re.search(r"\bped\b", t):
        out["reason_type"] = "pre_existing_disease"
        out["grounds"] = ["IRDAI caps the pre-existing disease waiting period at 36 months. If you are past that, the exclusion no longer applies.",
                          "Ask for the medical evidence that the condition existed before the policy started."]
    elif "waiting period" in t:
        out["reason_type"] = "waiting_period"
        out["grounds"] = ["Check the policy start date and any portability credit from an earlier policy. Waiting periods count from your first policy if you ported."]
    elif "not medically necessary" in t or "could have been treated" in t or "opd" in t:
        out["reason_type"] = "not_medically_necessary"
        out["grounds"] = ["Attach the treating doctor's certificate explaining why hospitalisation was needed. The treating doctor's opinion carries weight with the Ombudsman."]
    elif "document" in t:
        out["reason_type"] = "documents_missing"
        out.update(strength="strong", grounds=["Submit the missing documents and ask for re-assessment. A claim should not be closed only for documents that can still be provided."])
    out["grounds"].append("Under the IRDAI Master Circular (2024), every rejection must be approved by the insurer's claim review committee and the reason given in writing. Ask for a copy of that decision.")
    return out
