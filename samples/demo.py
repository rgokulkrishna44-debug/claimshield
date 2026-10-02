"""Demo data. Insurer and hospital names are fictional on purpose."""

POLICY_TEXT = """[Page 1]
SURAKSHA FAMILY HEALTH PLAN - POLICY SCHEDULE
Insurer: Bharat Sample General Insurance Ltd (fictional, for demo)
Sum Insured: Rs 5,00,000 per policy year (family floater)
Policy start date: 01 April 2021. Continuous cover with no break.

[Page 4]
Section 3.1 Room Rent: Room, boarding and nursing expenses are payable up to 1% of the Sum Insured per day.
Section 3.2 ICU: Intensive care unit charges are payable up to 2% of the Sum Insured per day.
Section 3.3 Proportionate Deduction: If the insured person occupies a room with rent higher than the eligible limit, all associated medical expenses shall be payable in the same proportion as the eligible room rent bears to the actual room rent. Pharmacy, consumables, implants, medical devices and diagnostics are not subject to proportionate deduction.

[Page 6]
Section 4.2 Co-payment: A co-payment of 10% applies to every admissible claim where the insured person is aged 60 years or above at the time of admission.
Section 4.5 Sub-limits: Cataract surgery is payable up to Rs 40,000 per eye.

[Page 9]
Section 5.1 Pre-existing diseases are covered after 36 months of continuous coverage from the first policy start date.
Section 5.3 Items listed in List I of the IRDAI guidelines (non-payable items) are excluded unless the optional Consumables Cover is opted. Consumables Cover: Not opted.
"""

POLICY = {
    "insurer": "Bharat Sample General Insurance (demo)",
    "plan_name": "Suraksha Family Health Plan",
    "sum_insured": 500000,
    "room_rent_limit_pct_si": 1.0,
    "icu_limit_pct_si": 2.0,
    "copay_pct": 0,
    "consumables_cover": False,
    "sub_limits": {"cataract": 40000},
}

CLAUSES = [
    {"topic": "Room rent", "quote": "Room, boarding and nursing expenses are payable up to 1% of the Sum Insured per day.",
     "plain_english": "For Rs 5 lakh cover, the room can cost up to Rs 5,000 a day."},
    {"topic": "Proportionate deduction", "quote": "all associated medical expenses shall be payable in the same proportion as the eligible room rent bears to the actual room rent.",
     "plain_english": "If you take a costlier room, doctor, nursing and surgery fees are also cut by the same ratio."},
    {"topic": "ICU", "quote": "Intensive care unit charges are payable up to 2% of the Sum Insured per day.",
     "plain_english": "ICU is paid up to Rs 10,000 a day."},
    {"topic": "Sub-limit", "quote": "Cataract surgery is payable up to Rs 40,000 per eye.",
     "plain_english": "Cataract surgery has its own cap of Rs 40,000."},
    {"topic": "Pre-existing diseases", "quote": "Pre-existing diseases are covered after 36 months of continuous coverage",
     "plain_english": "Old illnesses are covered after 3 years with this insurer."},
    {"topic": "Consumables", "quote": "Consumables Cover: Not opted.",
     "plain_english": "Gloves, masks and similar items on IRDAI's non-payable list will not be paid."},
]

BILL = {
    "hospital": "Sri Lakshmi Multispeciality Hospital, Coimbatore (fictional)",
    "treatment": "Laparoscopic appendectomy",
    "differential_billing": True,
    "items": [
        {"description": "Room rent - Deluxe single room (3 days)", "amount": 24000, "days": 3},
        {"description": "Nursing charges", "amount": 4500},
        {"description": "Surgeon fees", "amount": 45000},
        {"description": "Anaesthetist fees", "amount": 12000},
        {"description": "OT charges", "amount": 18000},
        {"description": "Doctor visit charges", "amount": 6000},
        {"description": "Pharmacy - medicines and injections", "amount": 15600},
        {"description": "Surgical consumables (syringes, cannula, sutures)", "amount": 6200},
        {"description": "Lab tests and CT scan", "amount": 9800},
        {"description": "Gloves and masks", "amount": 1450},
        {"description": "Admission kit", "amount": 950},
        {"description": "Attendant food charges", "amount": 2100},
        {"description": "Medical records and photocopy charges", "amount": 400},
        {"description": "Registration charges", "amount": 500},
    ],
}

REJECTION_LETTER = """Bharat Sample General Insurance Ltd (fictional, for demo)
Claim No: CL/2026/48213   Policy No: SFHP/21/0099812
Date: 18 September 2026

Dear Policyholder,
We regret to inform you that your claim for hospitalisation at Sri Lakshmi Multispeciality Hospital from 10/09/2026 to 13/09/2026 for diabetes related complications has been repudiated.
Reason: Non-disclosure of pre-existing diabetes at the time of taking the policy. As per our investigation the insured was on diabetes medication since 2019, which was not disclosed in the proposal form.
The claim is therefore not admissible under the policy terms.
Claims Department
"""
