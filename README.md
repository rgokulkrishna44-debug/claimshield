# ClaimShield

An AI that protects Indian families from health insurance claim cuts and rejections.
Hack-A-Throne 2026 · Domain: FinTech & Digital Economy

## What it does

1. **Know your policy.** Upload the policy PDF. ClaimShield pulls out room rent limits, ICU limits, co-pay and sub-limits, then explains the key clauses in plain language. You can ask questions and get the exact policy line back.
2. **Check the discharge bill.** Upload the hospital bill. Every line is checked against your policy and IRDAI rules, and you see exactly how much the insurer will pay, how much you'll pay, and which lines the hospital should remove. A 3-hour timer tracks IRDAI's discharge approval deadline.
3. **Fight a rejection.** Upload the rejection letter. ClaimShield checks it against your policy and IRDAI rules (moratorium, PED waiting period, claim review committee), rates your case, and drafts the complaint letter. It also shows the path: insurer, then Bima Bharosa, then the Insurance Ombudsman.

## Why the numbers can be trusted

AI reads documents. **Money maths is plain Python** (`app/engine.py`) using fixed IRDAI rules (`app/rules.py`):
- IRDAI List I (not payable) and Lists II to IV (included in room, procedure or treatment charges)
- Room rent proportionate deduction, never applied to pharmacy, consumables, implants, diagnostics or ICU (IRDAI, June 2020)
- No proportionate deduction when the hospital doesn't charge differently by room type
- Co-pay, sub-limits, sum insured cap

## Run it

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8077
# open http://localhost:8077 and click the "Use demo" buttons
```

Optional keys (copy `.env.example`):
- `ANTHROPIC_API_KEY`: turns on AI reading of PDFs and bill photos, policy Q&A, rejection analysis and translation (Claude Opus 5.5).
- `BHASHINI_USER_ID`, `BHASHINI_API_KEY`: Government of India's Bhashini for Indian language translation (free at bhashini.gov.in).

Without any key, the app still runs on the rule engine and text parsing.

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Deploy

`render.yaml` is ready for Render: connect the GitHub repo, then add the keys as environment variables.

## Structure

```
app/rules.py      IRDAI rule base (fixed data)
app/engine.py     bill audit maths
app/extract.py    reading policy, bill and rejection documents (AI + fallback)
app/grievance.py  complaint letter and escalation steps
app/translate.py  Bhashini, then Claude, for Indian languages
app/main.py       FastAPI routes
static/           web app (HTML, CSS, JS)
samples/demo.py   fictional demo policy, bill and rejection letter
```

ClaimShield explains and drafts. It is not legal advice; the user decides what to send.
