"""Masks personal details in text before it is sent to an AI model.

India's DPDP Act 2023 asks for data minimisation: the AI only needs the charges and the policy
terms, not who the patient is. Names, phone numbers, emails, Aadhaar and PAN numbers, and
policy, claim and hospital record numbers are replaced with labels like [NAME] and [PHONE].
"""

import re

_LABELLED = [
    (r"(patient(?:'s)?\s+name|name\s+of\s+(?:the\s+)?(?:patient|insured|proposer)|insured\s+name|"
     r"policy\s*holder(?:\s+name)?|proposer(?:\s+name)?|attendant\s+name|name)\s*[:\-]\s*([^\n,;]{2,60})", "[NAME]"),
    (r"(policy\s*(?:no|number|#)\.?)\s*[:\-]?\s*([A-Z0-9/\-]{5,})", "[POLICY NO]"),
    (r"(claim\s*(?:no|number|id|#)\.?)\s*[:\-]?\s*([A-Z0-9/\-]{5,})", "[CLAIM NO]"),
    (r"(uhid|ip\s*no|mrn|reg(?:istration)?\s*no|admission\s*no|bill\s*no)\.?\s*[:\-]?\s*([A-Z0-9/\-]{3,})", "[RECORD NO]"),
    (r"(address)\s*[:\-]\s*([^\n]{5,120})", "[ADDRESS]"),
]
_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)"), "[AADHAAR]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
]


def mask_text(text: str) -> str:
    out = text
    for pattern, label in _LABELLED:
        out = re.sub(pattern, lambda m, lab=label: f"{m.group(1)}: {lab}", out, flags=re.I)
    for rx, label in _PATTERNS:
        out = rx.sub(label, out)
    return out
