# ClaimShield

Know what you will pay before you pay the hospital.

**Live:** https://rgokulkrishna44-debug.github.io/claimshield/ (free, works on any phone, nothing is uploaded)

In FY24, Indian health insurers cut or rejected claims worth ₹26,000 crore, up 19% in a year
(IRDAI annual report, reported by Business Standard, 27 Dec 2024). Families find out at the
billing counter, after the decisions that cost them most were already made. ClaimShield helps at
the three moments that decide what a family pays.

## What it does

1. **Before admission: pick the right room.** A room above the policy limit doesn't only cost the
   extra rent. The insurer cuts doctor, nursing and surgery fees in the same ratio. In the sample,
   the same appendix surgery costs the family ₹5,400 in an eligible ₹5,000 room and ₹46,463 in an
   ₹8,000 room.
2. **At discharge: check the bill.** Read the bill from a photo or PDF on the phone, check every
   line, then see what insurance pays, what you pay, and the IRDAI rule behind every rupee. It flags
   items that are already part of room or procedure charges and must not be billed again, and cuts
   the insurer isn't allowed to make. A 3 hour clock tracks IRDAI's discharge approval rule. After 3
   hours, extra hospital charges are the insurer's to pay.
3. **After a rejection: fight back.** Checks the insurer's letter against IRDAI rules (5 year
   moratorium, 36 month cap on waiting periods for earlier illnesses, Claims Review Committee),
   rates the case, writes the complaint letter and gives the escalation path with dates: insurer,
   Bima Bharosa, Insurance Ombudsman.

English, Tamil and Hindi. A WhatsApp summary to share with family. What to say at the desk.

## Why the numbers can be trusted

AI only turns documents into data. Every rupee is calculated by a fixed rule engine.

- **One rule file** (`static/rules.json`) holds IRDAI Lists I to IV, checked item by item against
  circular IRDAI/HLT/REG/CIR/176/09/2019 (27 Sep 2019). The server (`app/rules.py`) and the web
  app (`static/engine.js`) both read it.
- **Proportionate deduction** follows IRDAI's June 2020 rules: never on medicines, consumables,
  implants, diagnostics or ICU, and not at all when a hospital charges the same for every room.
- **Two engines, one answer.** `tests/test_parity.py` runs the Python and browser engines on 600
  random bills and 60 room comparisons and fails on any difference in a rupee, status or rule.
- **No false alarms on medicines.** Tests make sure lines like `CAP OMEZ 20MG`, `Tissue culture` or
  `Diabetic foot ulcer debridement` are never flagged.

## Privacy

The web version runs entirely in the browser. Bills, policies and letters never leave the phone.
PDFs are read with pdf.js and photos with Tesseract, on the device. The optional server version
can use AI for better reading. Before any text reaches the AI, `app/privacy.py` masks names, phone
numbers, emails, Aadhaar, PAN, and policy, claim and hospital record numbers. Nothing is stored.

## Run it

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8077     # server version, open http://localhost:8077
.venv/bin/python scripts/build_pages.py        # rebuild the free web version in docs/
```

`ANTHROPIC_API_KEY` is optional and turns on AI reading in the server version (Claude Opus 5.5).
Without it everything still works on the rule engine and on device reading.

## Tests

```bash
.venv/bin/python -m pytest -q     # 19 tests, node is needed for the parity tests
```

They cover the IRDAI lists, the room choice maths, Python and browser parity, phone and server
reading parity, personal data masking, and a house style check that no screen in any language has
hyphens, dashes or emojis.

## Structure

```
static/rules.json   IRDAI rules, the single source of truth
static/engine.js    rule engine for the browser
static/read.js      reading PDFs and photos on the phone
static/reject.js    rejection check, complaint letter, escalation steps
static/i18n.js      English, Tamil, Hindi
static/app.js       the web app
app/engine.py       the same rule engine for the server
app/extract.py      AI reading with text fallbacks
app/privacy.py      masks personal details before AI
app/main.py         FastAPI routes
docs/               built copy served by GitHub Pages
```

ClaimShield explains a policy and IRDAI rules. It is not legal advice. Check with your insurer
before you act. Sample insurer, hospital and people are made up.
