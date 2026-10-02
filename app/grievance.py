"""Complaint letters and the escalation path for a rejected or underpaid claim."""

from datetime import date, timedelta

ESCALATION = [
    {
        "step": 1,
        "to": "Insurer's Grievance Redressal Officer",
        "how": "Email the insurer's grievance ID (on their website and policy document). Keep the acknowledgement number.",
        "wait": "Insurer should resolve within 14 days of receiving the complaint.",
        "days": 14,
    },
    {
        "step": 2,
        "to": "IRDAI Bima Bharosa portal",
        "how": "File at bimabharosa.irdai.gov.in, or call the IRDAI toll free number 155255, quoting step 1's reference.",
        "wait": "Use this if the insurer does not reply in time or the reply is unsatisfactory.",
        "days": 30,
    },
    {
        "step": 3,
        "to": "Insurance Ombudsman (free, no lawyer needed)",
        "how": "File online at cioins.co.in with the insurer's final reply. Pick the Ombudsman office for your area.",
        "wait": "File within 1 year of the insurer's final reply. If the insurer ignores an Ombudsman award beyond 30 days, IRDAI rules make it pay Rs 5,000 per day.",
        "days": None,
    },
]


def timeline(start: date = None):
    start = start or date.today()
    out, d = [], start
    for s in ESCALATION:
        item = dict(s)
        item["start_by"] = d.isoformat()
        if s["days"]:
            d = d + timedelta(days=s["days"])
        out.append(item)
    return out


def complaint_letter(analysis: dict, details: dict) -> str:
    name = details.get("name") or "[Your name]"
    policy_no = details.get("policy_no") or "[Policy number]"
    claim_no = details.get("claim_no") or "[Claim number]"
    insurer = details.get("insurer") or "[Insurer name]"
    patient = details.get("patient") or name
    hospital = details.get("hospital") or "[Hospital name]"
    amount = details.get("amount")
    amount_line = f"Amount disputed: Rs {float(amount):,.0f}\n" if amount else ""

    grounds = analysis.get("grounds") or []
    clauses = analysis.get("policy_clauses_cited") or []
    docs = analysis.get("documents_to_attach") or []

    lines = [
        f"Date: {date.today().strftime('%d %B %Y')}",
        "",
        "To,",
        "The Grievance Redressal Officer,",
        f"{insurer}",
        "",
        f"Subject: Request to review rejection/deduction of claim no. {claim_no} under policy no. {policy_no}",
        "",
        "Dear Sir/Madam,",
        "",
        f"I, {name}, am writing about the claim for {patient}'s treatment at {hospital}. "
        f"The claim was rejected or reduced with the reason: \"{analysis.get('insurer_reason', '').strip()[:300]}\".",
        "",
        amount_line + "I request you to review this decision for the following reasons:",
        "",
    ]
    for i, g in enumerate(grounds, 1):
        lines.append(f"{i}. {g}")
    if clauses:
        lines += ["", "Relevant policy clauses:"]
        lines += [f"- {c}" for c in clauses]
    lines += [
        "",
        "As required by the IRDAI Master Circular on Health Insurance (29 May 2024), please also share "
        "the claim review committee's decision and the specific policy clause relied on for this rejection.",
        "",
        "I request you to reconsider and settle the claim in full within 14 days. If not resolved, I will "
        "approach IRDAI's Bima Bharosa portal and the Insurance Ombudsman.",
        "",
    ]
    if docs:
        lines += ["Documents attached:"] + [f"- {d}" for d in docs] + [""]
    lines += ["Yours sincerely,", name, details.get("phone") or "[Phone]", details.get("email") or "[Email]"]
    return "\n".join(lines)
