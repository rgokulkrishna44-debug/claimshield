"""Indian language support.

Order of preference:
  1. Bhashini (Govt of India, MeitY) if BHASHINI_USER_ID and BHASHINI_API_KEY are set.
  2. Claude, if an Anthropic key is set.
  3. Return the English text unchanged.

Bhashini adapter follows the ULCA pipeline API (config call, then compute call). It has not been
tested against a live Bhashini account yet; register at bhashini.gov.in to get keys.
"""

import os

import httpx2 as httpx

from . import llm

LANGS = {"en": "English", "ta": "Tamil", "hi": "Hindi", "te": "Telugu", "kn": "Kannada",
         "ml": "Malayalam", "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati"}

BHASHINI_CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
BHASHINI_PIPELINE_ID = os.getenv("BHASHINI_PIPELINE_ID", "64392f96daac500b55c543cd")


def _bhashini(text, target):
    uid, key = os.getenv("BHASHINI_USER_ID"), os.getenv("BHASHINI_API_KEY")
    if not (uid and key):
        return None
    lang = {"sourceLanguage": "en", "targetLanguage": target}
    cfg = httpx.post(
        BHASHINI_CONFIG_URL,
        headers={"userID": uid, "ulcaApiKey": key},
        json={"pipelineTasks": [{"taskType": "translation", "config": {"language": lang}}],
              "pipelineRequestConfig": {"pipelineId": BHASHINI_PIPELINE_ID}},
        timeout=20,
    ).json()
    endpoint = cfg["pipelineInferenceAPIEndPoint"]
    service_id = cfg["pipelineResponseConfig"][0]["config"][0]["serviceId"]
    auth = endpoint["inferenceApiKey"]
    res = httpx.post(
        endpoint["callbackUrl"],
        headers={auth["name"]: auth["value"]},
        json={"pipelineTasks": [{"taskType": "translation", "config": {"language": lang, "serviceId": service_id}}],
              "inputData": {"input": [{"source": text}]}},
        timeout=30,
    ).json()
    return res["pipelineResponse"][0]["output"][0]["target"]


def translate(text: str, target: str):
    """Returns (translated_text, engine)."""
    if target == "en" or not text.strip():
        return text, "none"
    try:
        out = _bhashini(text, target)
        if out:
            return out, "bhashini"
    except Exception:
        pass
    try:
        out = llm.ask_text(
            f"Translate the user's text into simple, everyday {LANGS.get(target, target)} that a family "
            "in a small Indian town would understand. Keep rupee amounts, numbers, and names of rules "
            "(IRDAI, Bima Bharosa, Ombudsman) as they are. Output only the translation.",
            [{"type": "text", "text": text}], effort="low")
        return out, "claude"
    except llm.LLMUnavailable:
        return text, "none"
