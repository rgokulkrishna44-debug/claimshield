from fastapi.testclient import TestClient

from app import rules
from app.engine import Bill, BillItem, Policy, audit
from app.main import app
from samples import demo


def test_demo_bill_numbers():
    r = audit(Policy(**demo.POLICY), Bill(**demo.BILL))
    assert r.total_billed == 146500
    assert r.room_ratio == 0.625  # Rs 5,000 limit vs Rs 8,000/day room
    by = {l.description: l for l in r.lines}
    assert by["Room rent - Deluxe single room (3 days)"].payable == 15000
    assert by["Surgeon fees"].payable == 28125  # proportionate deduction
    assert by["Pharmacy - medicines and injections"].cut == 0  # IRDAI: no proportionate cut
    assert by["Lab tests and CT scan"].cut == 0
    assert by["Gloves and masks"].payable == 0  # List I
    assert r.insurer_pays + r.you_pay == r.total_billed


def test_no_proportionate_when_hospital_has_flat_pricing():
    bill = Bill(**{**demo.BILL, "differential_billing": False})
    r = audit(Policy(**demo.POLICY), bill)
    surgeon = next(l for l in r.lines if l.description == "Surgeon fees")
    assert surgeon.cut == 0
    assert any("must NOT be applied" in s for s in r.summary)


def test_copay_and_sub_limit():
    p = Policy(sum_insured=300000, copay_pct=20, sub_limits={"cataract": 40000})
    b = Bill(treatment="Cataract surgery right eye", items=[BillItem(description="Cataract package", amount=60000)])
    r = audit(p, b)
    assert r.sub_limit_cut == 20000
    assert r.copay == 8000
    assert r.insurer_pays == 32000


def test_consumables_addon_pays_list_i():
    p = Policy(sum_insured=500000, consumables_cover=True)
    r = audit(p, Bill(items=[BillItem(description="Gloves", amount=500)]))
    assert r.insurer_pays == 500


def test_keyword_matching_is_whole_word():
    assert rules.match_irdai_list("Capsule Pantoprazole") is None
    assert rules.match_irdai_list("Surgical cap")[0] == "list_ii"
    assert rules.guess_category("ICU charges") == "icu"
    assert rules.guess_category("Doctor visit") == "doctor"


def test_api_flow_without_ai(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    c = TestClient(app)
    pid = c.post("/api/policy/demo").json()["policy_id"]
    r = c.post("/api/audit", json={"policy_id": pid, "bill": demo.BILL}).json()
    assert r["insurer_pays"] > 0
    rej = c.post("/api/rejection", data={"policy_id": pid, "years_insured": 5.5, "letter_text": demo.REJECTION_LETTER}).json()
    assert rej["analysis"]["reason_type"] == "non_disclosure"
    assert rej["analysis"]["strength"] == "strong"
    assert "Grievance Redressal Officer" in rej["letter"]
    ans = c.post("/api/policy/ask", json={"policy_id": pid, "question": "What is the room rent limit?"}).json()
    assert "Room" in ans["answer"]
