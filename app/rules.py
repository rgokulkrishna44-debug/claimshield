"""IRDAI rule base used by the audit engine.

Everything here is fixed data, not AI output, so the bill audit is repeatable and explainable.
Sources (verify against the latest IRDAI text before relying on them for a real claim):
  - IRDAI Guidelines on Standardization in Health Insurance, Annexure: List I (items not payable),
    Lists II, III, IV (items subsumed into room, procedure and treatment charges).
  - IRDAI guidance on proportionate deduction (June 2020): no proportionate deduction on pharmacy,
    consumables, implants, medical devices, diagnostics, or ICU charges.
  - IRDAI Master Circular on Health Insurance (29 May 2024): cashless decision within 1 hour,
    final discharge authorisation within 3 hours, rejections need claim review committee approval.
"""

import re

CITE_LIST_I = "IRDAI Standardization Guidelines, List I (items not payable)"
CITE_LIST_II = "IRDAI Standardization Guidelines, List II (subsumed into room charges)"
CITE_LIST_III = "IRDAI Standardization Guidelines, List III (subsumed into procedure charges)"
CITE_LIST_IV = "IRDAI Standardization Guidelines, List IV (subsumed into cost of treatment)"
CITE_PROPORTIONATE = "IRDAI guidance on proportionate deduction (June 2020)"
CITE_MASTER_2024 = "IRDAI Master Circular on Health Insurance (29 May 2024)"

# List I: not payable at all (unless the policy has a consumables add-on).
LIST_I = [
    "baby food", "baby utilit*", "beauty", "belt", "brace", "buds", "cold pack", "hot pack",
    "carry bag", "email", "internet", "leggings", "laundry", "mineral water", "sanitary pad",
    "telephone", "guest service", "crepe bandage", "diaper", "eyelet collar", "sling",
    "television", "tv charge", "surcharge", "attendant", "extra diet", "birth certificate",
    "certificate charge", "courier", "conveyance", "medical certificate", "medical record",
    "photocop*", "mortuary", "walking aid", "spacer", "spirometer", "nebulizer kit", "nebuliser kit",
    "steam inhaler", "thermometer", "cervical collar", "splint", "diabetic foot", "knee immobil*",
    "lumbo sacral", "air bed", "water bed", "private nurse", "sugar free", "cream", "powder",
    "lotion", "toiletr*", "ecg electrode", "glove", "kidney tray", "mask", "ounce glass",
    "pelvic traction", "pan can", "trolley cover", "urometer", "urine jug", "food charge",
    "visitor", "registration fee for donor",
]

# List II: part of room charges, should not be billed separately.
LIST_II = [
    "hand wash", "shoe cover", "cap", "cradle", "comb", "eau-de-cologne", "foot cover", "gown",
    "slipper", "tissue", "tooth paste", "toothpaste", "tooth brush", "toothbrush", "bed pan",
    "sputum cup", "disinfectant lotion", "luxury tax", "hvac", "housekeeping", "house keeping",
    "air condition*", "clean sheet", "blanket", "admission kit", "diabetic chart",
    "documentation charge", "discharge procedure", "daily chart", "entrance pass", "file opening",
    "incidental", "misc*", "name tag", "identification band", "pulse oximeter", "pulseoxymeter",
]

# List III: part of procedure / surgery charges.
LIST_III = [
    "hair removal", "razor", "eye pad", "eye shield", "camera cover", "dvd", "cd charge",
    "gauze", "theatre booking", "ward booking", "microscope cover", "surgical blade",
    "harmonic scalpel", "shaver", "surgical drill", "eye kit", "eye drape", "x-ray film",
    "boyles apparatus", "cotton", "surgical tape", "apron", "tourniquet", "torniquet",
    "orthobundle", "gynaec bundle",
]

# List IV: part of cost of treatment.
LIST_IV = [
    "admission charge", "registration charge", "urine container", "blood reservation",
    "ante natal booking", "bipap", "cpap", "infusion pump", "hydrogen peroxide", "spirit",
    "nutrition planning", "dietician", "diet charge", "hiv kit", "mouthwash", "lozenge",
    "mouth paint", "vaccination", "alcohol swab", "scrub solution", "sterillium", "glucometer",
    "urine bag",
]

# Bill categories. Only "associated medical expenses" get proportionate deduction.
CATEGORIES = [
    "room", "icu", "doctor", "nursing", "procedure", "pharmacy", "consumables", "implants",
    "diagnostics", "other",
]
ASSOCIATED_EXPENSES = {"doctor", "nursing", "procedure", "other"}
NO_PROPORTIONATE = {"pharmacy", "consumables", "implants", "diagnostics", "icu"}

CATEGORY_KEYWORDS = {
    "icu": ["icu", "iccu", "nicu", "picu", "intensive care", "hdu", "ccu"],
    "room": ["room", "ward", "bed charge", "accommodation", "boarding"],
    "doctor": ["consult*", "doctor", "physician", "visit", "specialist", "anaesthetist", "anesthetist", "rmo", "professional fee"],
    "nursing": ["nursing"],
    "procedure": ["surgeon", "surgery", "operation", "ot charge", "theatre", "procedure",
                  "anaesthesia", "anesthesia", "package"],
    "implants": ["implant", "stent", "lens", "iol", "prosthe*", "pacemaker", "plate", "screw"],
    "diagnostics": ["lab", "test", "x-ray", "xray", "scan", "mri", "ct", "ultrasound", "usg",
                    "ecg", "echo", "blood", "patholog*", "radiolog*", "culture", "cbc"],
    "pharmacy": ["pharmacy", "medicine", "drug", "tablet", "injection", "inj", "iv fluid",
                 "antibiotic", "syrup"],
    "consumables": ["consumable", "syringe", "cannula", "catheter", "dressing", "suture",
                    "bandage", "disposable"],
}

LISTS = [
    ("list_i", LIST_I, CITE_LIST_I),
    ("list_ii", LIST_II, CITE_LIST_II),
    ("list_iii", LIST_III, CITE_LIST_III),
    ("list_iv", LIST_IV, CITE_LIST_IV),
]


def _kw_regex(w):
    """Whole-word match by default; a trailing '*' means prefix match (e.g. 'photocop*')."""
    if w.endswith("*"):
        return re.compile(r"\b" + re.escape(w[:-1]))
    return re.compile(r"\b" + re.escape(w) + r"s?\b")


_LIST_PATTERNS = [(lid, [(w, _kw_regex(w)) for w in words], cite) for lid, words, cite in LISTS]
_CAT_PATTERNS = {c: [_kw_regex(w) for w in ws] for c, ws in CATEGORY_KEYWORDS.items()}
_CAT_ORDER = ["icu", "room", "implants", "procedure", "nursing", "doctor", "consumables",
              "diagnostics", "pharmacy"]


def match_irdai_list(description):
    """Return (list_id, keyword, citation) if the item is on an IRDAI list, else None."""
    d = description.lower()
    for list_id, pats, cite in _LIST_PATTERNS:
        for w, rx in pats:
            if rx.search(d):
                return list_id, w.rstrip("*"), cite
    return None


def guess_category(description):
    d = description.lower()
    for cat in _CAT_ORDER:
        if any(rx.search(d) for rx in _CAT_PATTERNS[cat]):
            return cat
    return "other"
