"""The phone and the server must read bills and rejection letters the same way, and the server
must never send personal details to the AI."""

import json
import subprocess
from pathlib import Path

import pytest

from app import extract
from app.privacy import mask_text
from samples import demo
from tests.test_parity import NODE

ROOT = Path(__file__).resolve().parent.parent

BILLS = [
    "Room Rent Deluxe (3 days)   24,000.00\nSurgeon fees 45000\nGRAND TOTAL 69,000\nGST 18% 1,200",
    "1. Pharmacy  Rs. 15,600/-\n2) Lab tests and CT scan : 9,800\nUHID: KMH204581\nGloves and masks | 1450",
    "Nursing charges 3 1500 4500\nAdvance paid 20000\nBalance 10,000\nOT charges ₹ 18,000.50",
]
LETTERS = [
    (demo.REJECTION_LETTER, 5.5),
    (demo.REJECTION_LETTER, 2),
    ("Reason: Pre-existing hypertension excluded during the waiting period.", 4),
    ("Reason: Hospitalisation was less than 24 hours.", 1),
    ("Reason: Treatment could have been taken on OPD basis.", 1),
    ("Reason: Discharge summary and bills not submitted.", 1),
    ("Reason: Claim intimation was received late.", 1),
    ("Reason: Proportionate deduction applied as room rent exceeded the limit.", 1),
    ("Your claim is not payable as per policy terms.", 0),
]


@pytest.mark.skipif(not Path(NODE).exists(), reason="node not installed")
def test_phone_and_server_read_alike():
    cases = {"bills": BILLS, "letters": LETTERS}
    out = subprocess.run([NODE, str(ROOT / "scripts" / "reader_runner.js")], input=json.dumps(cases),
                         capture_output=True, text=True, check=True)
    js = json.loads(out.stdout)
    for text, got in zip(cases["bills"], js["bills"]):
        py = [i.model_dump(exclude={"category"}) for i in extract.bill_from_text(text).items]
        assert len(py) >= 2, text  # each sample has several real charge lines
        assert py == got, (text, py, got)
    for (text, years), got in zip(LETTERS, js["letters"]):
        py = extract._rejection_heuristic(text, years)
        assert py["ground_codes"] == got["grounds"], (text, py["ground_codes"], got["grounds"])
        assert py["strength"] == got["strength"] and py["reason_type"] == got["reason_type"], text


def test_bill_parser_skips_totals_and_keeps_charges():
    items = extract.bill_from_text("Room Rent Deluxe (3 days) 24,000.00\nGRAND TOTAL 69,000\nAdvance paid 20000\nSurgeon fees 45000").items
    assert [(i.description, i.amount, i.days) for i in items] == [("Room Rent Deluxe (3 days)", 24000, 3), ("Surgeon fees", 45000, None)]


def test_demo_rejection_is_strong_after_five_years():
    r = extract._rejection_heuristic(demo.REJECTION_LETTER, 5.5)
    assert r["strength"] == "strong" and r["ground_codes"] == ["G_MORATORIUM", "G_PED_CAP", "G_CRC"]


def test_personal_details_are_masked_before_ai():
    text = ("Patient Name: Ramesh Kumar\nPolicy No: SFHP/21/0099812\nPhone: +91 98765 43210\n"
            "Aadhaar 1234 5678 9012 PAN ABCDE1234F\nemail ramesh.k@gmail.com\nSurgeon fees 45,000")
    masked = mask_text(text)
    for secret in ["Ramesh", "0099812", "98765", "1234 5678 9012", "ABCDE1234F", "ramesh.k@gmail.com"]:
        assert secret not in masked
    assert "45,000" in masked
    block = extract._content_for(text.encode(), "text/plain", "hint")[0]["text"]
    assert "Ramesh" not in block and "45,000" in block
