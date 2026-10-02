"""IRDAI rule base used by the audit engine.

The rules live in one data file, static/rules.json, so the server (this module) and the web app
(static/engine.js) read exactly the same lists. Nothing here is AI output, so every audit is
repeatable and explainable.

Sources, checked item by item:
  - IRDAI circular IRDAI/HLT/REG/CIR/176/09/2019 (27 Sep 2019): List I (items not payable),
    Lists II, III, IV (items included in room, procedure and treatment charges).
  - IRDAI circular on proportionate deductions (June 2020): no proportionate deduction on
    pharmacy and consumables, implants and medical devices, diagnostics, or ICU charges, and none
    at all when the hospital does not charge differently by room type.
  - IRDAI Master Circular on Health Insurance Business (29 May 2024): cashless decision within
    1 hour, final discharge approval within 3 hours, extra hospital charges after that paid by the
    insurer, rejections only with the Claims Review Committee's approval.
"""

import json
import re
from pathlib import Path

RULES_FILE = Path(__file__).resolve().parent.parent / "static" / "rules.json"
DATA = json.loads(RULES_FILE.read_text(encoding="utf-8"))

CITES = {
    "R_LIST_I": "IRDAI List I, items insurers do not pay (circular dated 27 Sep 2019)",
    "R_LIST_II": "IRDAI List II, items included in room charges (circular dated 27 Sep 2019)",
    "R_LIST_III": "IRDAI List III, items included in procedure charges (circular dated 27 Sep 2019)",
    "R_LIST_IV": "IRDAI List IV, items included in the cost of treatment (circular dated 27 Sep 2019)",
    "R_PD": "IRDAI rules on proportionate deduction (June 2020)",
    "R_POLICY_ROOM": "Your policy's room rent limit",
    "R_POLICY_ICU": "Your policy's ICU limit",
    "R_POLICY_PD": "Your policy's proportionate deduction clause",
}
CITE_MASTER_2024 = "IRDAI Master Circular on Health Insurance Business (29 May 2024)"

CATEGORIES = DATA["categories"]
ASSOCIATED_EXPENSES = set(DATA["associated"])
NO_PROPORTIONATE = set(DATA["no_pd"])


def _term_regex(term):
    """Whole word match with an optional plural s. A trailing * means prefix match."""
    if isinstance(term, dict):
        return re.compile(term["re"], re.I), term["w"], term.get("label", term["re"])
    if term.endswith("*"):
        return re.compile(r"\b" + re.escape(term[:-1]), re.I), len(term) - 1, term[:-1]
    return re.compile(r"\b" + re.escape(term) + r"s?\b", re.I), len(term), term


def _build():
    entries = []
    order = 0
    for group in DATA["groups"]:
        for term in group["terms"]:
            rx, weight, label = _term_regex(term)
            entries.append((weight, order, rx, label, group))
            order += 1
    # Longest term first; ties keep file order. Must match static/engine.js exactly.
    entries.sort(key=lambda e: (-e[0], e[1]))
    return entries


_ENTRIES = _build()
_CAT_PATTERNS = {c: [_term_regex(w)[0] for w in ws] for c, ws in DATA["category_keywords"].items()}
_CAT_ORDER = DATA["category_order"]


def match(description):
    """Return (group, matched_term) for the first IRDAI list entry that fits, else None."""
    for _, _, rx, label, group in _ENTRIES:
        if rx.search(description):
            return group, label
    return None


def match_irdai_list(description):
    """Backwards compatible helper: (list_id, term, citation) or None."""
    hit = match(description)
    if not hit:
        return None
    group, label = hit
    return group["id"], label, CITES[group["rule"]]


def guess_category(description):
    for cat in _CAT_ORDER:
        if any(rx.search(description) for rx in _CAT_PATTERNS[cat]):
            return cat
    return "other"
