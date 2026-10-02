"""Thin wrapper around the Claude API.

The app works without an API key (rule engine + keyword fallbacks). With ANTHROPIC_API_KEY set,
Claude reads policy PDFs, bills and rejection letters. Money maths never happens here.
"""

import base64
import json
import os

import anthropic

MODEL = os.getenv("CLAIMSHIELD_MODEL", "claude-opus-5-5")

_client = None


class LLMUnavailable(Exception):
    pass


def available():
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def file_block(data: bytes, mime: str):
    """Turn an uploaded file into a Claude content block (PDF document or image)."""
    b64 = base64.standard_b64encode(data).decode("utf-8")
    if mime == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    if mime in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
    raise ValueError(f"Unsupported file type: {mime}")


def _call(system, content, output_format=None, effort="medium"):
    if not available():
        raise LLMUnavailable("No ANTHROPIC_API_KEY set")
    output_config = {"effort": effort}
    if output_format:
        output_config["format"] = {"type": "json_schema", "schema": output_format}
    try:
        resp = _get_client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config=output_config,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError as e:
        raise LLMUnavailable(f"Claude API key rejected: {e}") from e
    except anthropic.RateLimitError as e:
        raise LLMUnavailable("Claude API rate limited, try again in a minute") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable("Could not reach Claude API") from e

    if resp.stop_reason == "refusal":
        raise LLMUnavailable("Claude declined this request")
    text = "".join(b.text for b in resp.content if b.type == "text")
    if resp.stop_reason == "max_tokens":
        raise LLMUnavailable("Claude response was cut off")
    return text


def ask_json(system, content, schema, effort="medium"):
    return json.loads(_call(system, content, output_format=schema, effort=effort))


def ask_text(system, content, effort="medium"):
    return _call(system, content, effort=effort)
