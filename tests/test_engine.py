from fastapi.testclient import TestClient

from app import rules
from app.engine import Bill, BillItem, Policy, audit, room_options
from app.main import app
from samples import demo


def test_demo_bill_numbers():
    r = audit(Policy(**demo.POLICY), Bill(**demo.BILL))
    assert r.total_billed == 146500
    assert r.room_ratio == 0.625  # Rs 5,000 limit vs Rs 8,000 a day room
    by = {l.description: l for l in r.lines}
    assert by["Room rent - Deluxe single room (3 days)"].payable == 15000
    assert by["Surgeon fees"].payable == 28125  # proportionate deduction
    assert by["Pharmacy - medicines and injections"].cut == 0  # IRDAI: no room cut on medicines
    assert by["Pharmacy - medicines and injections"].status == "protected"
    assert by["Lab tests and CT scan"].cut == 0
    assert by["Gloves and masks"].payable == 0  # List I
    assert by["Admission kit"].codes == ["SUBSUMED_ROOM"]  # List II
    assert by["Registration charges"].codes == ["SUBSUMED_TREATMENT"]  # List IV
    assert r.challengeable == 1450
    assert r.you_pay == 46462.5
    assert r.insurer_pays + r.you_pay == r.total_billed


def test_room_choice_is_the_biggest_lever():
    items = [BillItem(**i) for i in demo.BILL["items"][1:]]  # same bill without the room line
    eligible, deluxe = room_options(Policy(**demo.POLICY), items, [5000, 8000], days=3)
    assert eligible["you_pay"] == 5400  # only the items insurers never pay
    assert deluxe["you_pay"] == 46462.5
    assert deluxe["room_ratio"] == 0.625


def test_no_proportionate_when_hospital_has_flat_pricing():
    bill = Bill(**{**demo.BILL, "differential_billing": False})
    r = audit(Policy(**demo.POLICY), bill)
    surgeon = next(l for l in r.lines if l.description == "Surgeon fees")
    assert surgeon.cut == 0
    assert "SUM_NO_DIFF" in r.summary_codes


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


def test_official_lists_and_no_false_alarms():
    # Checked against IRDAI circular IRDAI/HLT/REG/CIR/176/09/2019.
    assert rules.match_irdai_list("Face mask")[0] == "list_ii"  # List II item 15, not List I
    assert rules.match_irdai_list("N95 mask")[0] == "list_i"
    assert rules.match_irdai_list("Visitors pass")[0] == "list_ii"  # List II item 32
    assert rules.match_irdai_list("Extra diet charges")[0] == "list_i"
    assert rules.match_irdai_list("Nebulisation kit")[0] == "list_i"
    assert rules.match_irdai_list("Vasofix safety")[0] == "list_i"
    assert rules.match_irdai_list("Hair removal cream")[0] == "list_iii"
    assert rules.match_irdai_list("Surgical cap")[0] == "list_ii"
    # Medicines and real procedures must never be flagged.
    for line in ["CAP OMEZ 20MG", "Capsule Pantoprazole", "Tissue culture", "Diabetic foot ulcer debridement",
                 "Tab Dolo 650", "Splinting procedure", "Combination therapy", "Doctor visit charges"]:
        assert rules.match_irdai_list(line) is None, line
    assert rules.guess_category("CAP OMEZ 20MG") == "pharmacy"
    assert rules.guess_category("ICU charges") == "icu"
    assert rules.guess_category("Doctor visit") == "doctor"


def test_prescribed_cream_is_a_check_not_a_cut():
    r = audit(Policy(sum_insured=500000), Bill(items=[BillItem(description="Silver sulfadiazine cream", amount=300)]))
    assert r.lines[0].payable == 300
    assert r.lines[0].status == "check"


def test_ambulance_depends_on_cover():
    line = [BillItem(description="Ambulance charges", amount=2000)]
    assert audit(Policy(sum_insured=500000), Bill(items=line)).you_pay == 2000
    assert audit(Policy(sum_insured=500000, ambulance_cover=True), Bill(items=line)).you_pay == 0


def test_service_charge_cut_only_when_nursing_is_billed():
    p = Policy(sum_insured=500000)
    alone = audit(p, Bill(items=[BillItem(description="Service charges", amount=1000)]))
    assert alone.lines[0].cut == 0
    both = audit(p, Bill(items=[BillItem(description="Service charges", amount=1000),
                                BillItem(description="Nursing charges", amount=3000)]))
    assert both.lines[0].codes == ["SERVICE_CHARGE"]
    assert both.lines[0].payable == 0


def test_icu_is_never_cut_for_room_choice():
    p = Policy(sum_insured=500000, room_rent_limit_per_day=5000)
    r = audit(p, Bill(items=[BillItem(description="Deluxe room", amount=20000, days=2),
                             BillItem(description="ICU charges", amount=30000, days=2)]))
    icu = r.lines[1]
    assert icu.payable == 30000
    assert "ICU_NO_PD" in icu.codes


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
