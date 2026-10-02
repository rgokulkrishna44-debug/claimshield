"""ClaimShield API: policy explainer, discharge bill audit, rejection fighter."""

import json
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from samples import demo

from . import extract, grievance, llm, translate
from .engine import Bill, Policy, audit

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD = 20 * 1024 * 1024
ALLOWED = {"application/pdf", "image/png", "image/jpeg", "image/webp", "text/plain"}

app = FastAPI(title="ClaimShield", version="0.1.0")

# In-memory policy store for the demo. Swap for a database before real users.
POLICIES = {}


def _store(policy, clauses, text):
    pid = uuid.uuid4().hex[:12]
    POLICIES[pid] = {"policy": policy, "clauses": clauses, "text": text}
    return pid


async def _read(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 20 MB)")
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED:
        raise HTTPException(415, "Upload a PDF, photo (PNG/JPG) or text file")
    return data, mime


@app.get("/api/status")
def status():
    return {
        "ai": llm.available(),
        "model": llm.MODEL if llm.available() else None,
        "bhashini": bool(os.getenv("BHASHINI_USER_ID") and os.getenv("BHASHINI_API_KEY")),
        "languages": translate.LANGS,
    }


# ---------- Policy ----------

@app.post("/api/policy/demo")
def policy_demo():
    policy = Policy(**demo.POLICY)
    pid = _store(policy, demo.CLAUSES, demo.POLICY_TEXT)
    return {"policy_id": pid, "policy": policy, "clauses": demo.CLAUSES, "used_ai": False}


@app.post("/api/policy/upload")
async def policy_upload(file: UploadFile = File(...)):
    data, mime = await _read(file)
    policy, clauses, text, used_ai = extract.extract_policy(data, mime)
    pid = _store(policy, clauses, text)
    return {"policy_id": pid, "policy": policy, "clauses": clauses, "used_ai": used_ai}


class Ask(BaseModel):
    policy_id: str
    question: str
    lang: str = "en"


@app.post("/api/policy/ask")
def policy_ask(body: Ask):
    p = POLICIES.get(body.policy_id)
    if not p:
        raise HTTPException(404, "Policy not found. Upload it again.")
    answer, used_ai = extract.ask_policy(body.question, p["text"], translate.LANGS.get(body.lang, "English"))
    engine = "claude" if used_ai else "none"
    if not used_ai and body.lang != "en":
        answer, engine = translate.translate(answer, body.lang)
    return {"answer": answer, "used_ai": used_ai, "translated_by": engine}


# ---------- Bill audit ----------

@app.get("/api/bill/demo")
def bill_demo():
    return demo.BILL


@app.post("/api/bill/upload")
async def bill_upload(file: UploadFile = File(...)):
    data, mime = await _read(file)
    bill, used_ai = extract.extract_bill(data, mime)
    if not bill.items:
        raise HTTPException(422, "Could not read any charges from this bill. Try a clearer photo or add lines by hand.")
    return {"bill": bill, "used_ai": used_ai}


class AuditRequest(BaseModel):
    policy_id: Optional[str] = None
    policy: Optional[Policy] = None
    bill: Bill
    lang: str = "en"


@app.post("/api/audit")
def run_audit(body: AuditRequest):
    policy = body.policy or (POLICIES.get(body.policy_id or "") or {}).get("policy")
    if not policy:
        raise HTTPException(400, "Load a policy first")
    result = audit(policy, body.bill)
    out = result.model_dump()
    out["summary_translated"] = None
    if body.lang != "en" and result.summary:
        text, engine = translate.translate("\n".join(result.summary), body.lang)
        out["summary_translated"] = {"text": text, "engine": engine}
    return out


# ---------- Rejection ----------

@app.get("/api/rejection/demo")
def rejection_demo():
    return {"letter": demo.REJECTION_LETTER}


@app.post("/api/rejection")
async def rejection(
    policy_id: str = Form(...),
    years_insured: float = Form(0),
    details: str = Form("{}"),
    letter_text: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    p = POLICIES.get(policy_id)
    if not p:
        raise HTTPException(404, "Policy not found. Load it again.")
    if file is not None and file.filename:
        data, mime = await _read(file)
    elif letter_text.strip():
        data, mime = letter_text.encode(), "text/plain"
    else:
        raise HTTPException(400, "Upload the rejection letter or paste its text")
    analysis, used_ai = extract.analyze_rejection(data, mime, p["text"], years_insured)
    try:
        info = json.loads(details or "{}")
    except json.JSONDecodeError:
        info = {}
    info.setdefault("insurer", p["policy"].insurer)
    return {
        "analysis": analysis,
        "used_ai": used_ai,
        "letter": grievance.complaint_letter(analysis, info),
        "timeline": grievance.timeline(),
    }


class TranslateRequest(BaseModel):
    text: str
    lang: str


@app.post("/api/translate")
def do_translate(body: TranslateRequest):
    text, engine = translate.translate(body.text, body.lang)
    return {"text": text, "engine": engine}


# ---------- Frontend ----------

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
