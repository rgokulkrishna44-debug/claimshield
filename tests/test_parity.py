"""The web app's engine (static/engine.js) must give the same answer as the server's (app/engine.py).

Runs both on 600 seeded random bills plus room choice comparisons, and fails on any difference in
a single rupee, status, reason code or rule.
"""

import json
import os
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from app.engine import Bill, BillItem, Policy, audit, room_options

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node") or os.path.expanduser("~/.local/node/bin/node")

WORDS = [
    "Room rent", "Deluxe room", "General ward", "ICU charges", "NICU", "Nursing charges", "Special nursing charges",
    "Surgeon fees", "OT charges", "Anaesthetist fees", "Doctor visit charges", "Consultation", "Pharmacy",
    "Tab Dolo 650", "CAP OMEZ 20MG", "Inj Ceftriaxone", "Surgical consumables", "Syringes", "Lab tests", "CT scan",
    "Tissue culture", "Knee implant", "Coronary stent", "Hernia mesh", "Gloves", "Gloves and masks", "Face mask",
    "N95 mask", "Admission kit", "Registration charges", "Attendant food charges", "Medical records", "Photocopy",
    "Visitors pass", "Silver sulfadiazine cream", "Body lotion", "Ambulance charges", "Service charges",
    "Extra diet charges", "Diet charges", "Cotton and gauze", "Hair removal cream", "Nebulisation kit", "Vasofix safety",
    "Donor blood grouping and cross matching", "Oxygen cylinder for home use", "Misc charges", "Housekeeping",
    "Diabetic foot ulcer debridement", "Splinting procedure", "Cataract package", "Physiotherapy", "Blood bank",
]
CATS = [None, None, None, "room", "icu", "doctor", "nursing", "procedure", "pharmacy", "consumables", "implants",
        "diagnostics", "other"]


def _policy(rng):
    si = rng.choice([100000, 200000, 300000, 500000, 1000000])
    p = {"sum_insured": si, "copay_pct": rng.choice([0, 0, 10, 20]),
         "consumables_cover": rng.random() < 0.2, "ambulance_cover": rng.random() < 0.5, "sub_limits": {}}
    mode = rng.random()
    if mode < 0.35:
        p["room_rent_limit_pct_si"] = rng.choice([1, 1, 2])
    elif mode < 0.7:
        p["room_rent_limit_per_day"] = rng.choice([2000, 3500, 5000, 7500])
    elif mode < 0.85:
        p["room_rent_limit_pct_si"], p["room_rent_limit_per_day"] = 1, rng.choice([3000, 6000])
    if rng.random() < 0.5:
        p["icu_limit_pct_si"] = 2
    if rng.random() < 0.3:
        p["sub_limits"] = {"cataract": rng.choice([25000, 40000])}
    return p


def _bill(rng):
    items = []
    for _ in range(rng.randint(1, 14)):
        desc = rng.choice(WORDS)
        cat = rng.choice(CATS)
        item = {"description": desc, "amount": round(rng.uniform(50, 60000), rng.choice([0, 2])), "category": cat}
        if cat in ("room", "icu") or "room" in desc.lower() or "icu" in desc.lower() or "ward" in desc.lower():
            item["days"] = rng.choice([None, 1, 2, 3, 5, 7])
        items.append(item)
    return {"treatment": rng.choice(["", "", "Cataract surgery", "Appendectomy"]),
            "differential_billing": rng.random() < 0.8, "items": items}


def _norm(x):
    return json.loads(json.dumps(x))


@pytest.mark.skipif(not Path(NODE).exists(), reason="node not installed")
def test_browser_engine_matches_python_engine():
    rng = random.Random(20261003)
    cases, expected = [], []
    for _ in range(600):
        pol, bill = _policy(rng), _bill(rng)
        cases.append({"policy": pol, "bill": bill})
        expected.append(audit(Policy(**pol), Bill(**bill)).model_dump())
    for _ in range(60):
        pol, bill = _policy(rng), _bill(rng)
        items = [i for i in bill["items"] if i.get("category") != "room"]
        rents = [rng.choice([1500, 3000, 5000, 8000, 12000]) for _ in range(3)]
        days = rng.choice([1, 3, 5])
        cases.append({"policy": pol, "items": items, "rents": rents, "days": days,
                      "differential_billing": bill["differential_billing"], "treatment": bill["treatment"]})
        expected.append(room_options(Policy(**pol), [BillItem(**i) for i in items], rents, days,
                                     bill["differential_billing"], bill["treatment"]))

    run = subprocess.run([NODE, str(ROOT / "scripts" / "parity_runner.js")], input=json.dumps(cases),
                         capture_output=True, text=True, check=True)
    got = json.loads(run.stdout)
    assert len(got) == len(expected)

    money = ["total_billed", "payable_before_copay", "copay", "sub_limit_cut", "insurer_pays", "you_pay", "challengeable"]
    for n, (py, js) in enumerate(zip(expected, got)):
        if isinstance(py, list):  # room options
            for a, b in zip(py, js):
                assert abs(a["you_pay"] - b["you_pay"]) < 0.011, (n, a, b)
                assert abs(a["insurer_pays"] - b["insurer_pays"]) < 0.011, (n, a, b)
                assert (a["room_ratio"] is None) == (b["room_ratio"] is None), (n, a, b)
            continue
        py, js = _norm(py), js
        for k in money:
            assert abs(py[k] - js[k]) < 0.011, (n, k, py[k], js[k], cases[n])
        if py["room_ratio"] is None:
            assert js["room_ratio"] is None, (n, cases[n])
        else:
            assert abs(py["room_ratio"] - js["room_ratio"]) < 1e-4, (n, cases[n])
        assert py["summary_codes"] == js["summary_codes"], (n, cases[n])
        for a, b in zip(py["lines"], js["lines"]):
            for k in ("category", "status", "codes", "rule_codes", "action_code"):
                assert a[k] == b[k], (n, k, a, b)
            for k in ("billed", "payable", "cut"):
                assert abs(a[k] - b[k]) < 0.011, (n, k, a, b)
