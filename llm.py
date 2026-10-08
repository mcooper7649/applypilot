"""
Shared Claude helper for the URL-intake, resume-parse and apply-assistant
features. Every call is schema-constrained (structured outputs), so callers get
a parsed dict back instead of scraping JSON out of free text.
"""
import json
import anthropic
from config import ANTHROPIC_API_KEY

MODEL = "claude-opus-5-5"

# Fail fast instead of the SDK default 10-minute timeout; the worker reports the error.
_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=180, max_retries=2)


class LLMError(RuntimeError):
    pass


def structured(prompt: str, schema: dict, *, document: dict | None = None,
               effort: str = "medium", max_tokens: int = 16000) -> dict:
    """Run one prompt and return JSON matching `schema`.

    `document` is an optional content block (e.g. a base64 PDF) placed before
    the prompt text.
    """
    content = ([document] if document else []) + [{"type": "text", "text": prompt}]
    resp = _client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        output_config={"effort": effort,
                       "format": {"type": "json_schema", "schema": schema}},
        # Server-side fallback: if a safety classifier declines, the API reruns
        # the request on a suitable model instead of returning nothing.
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
        messages=[{"role": "user", "content": content}],
    )
    if resp.stop_reason == "refusal":
        raise LLMError("model declined the request")
    if resp.stop_reason == "max_tokens":
        raise LLMError("response truncated (max_tokens)")
    text = next((b.text for b in reversed(resp.content) if b.type == "text"), None)
    if text is None:
        raise LLMError("no text in response")
    return json.loads(text)


def obj(props: dict, required: list | None = None) -> dict:
    """Small helper to build strict object schemas."""
    return {"type": "object", "properties": props,
            "required": list(props) if required is None else required,
            "additionalProperties": False}


STR = {"type": "string"}
STR_LIST = {"type": "array", "items": STR}
NUM_OR_NULL = {"type": ["number", "null"]}

# Shape of "facts about the candidate" extracted from a resume / website. Same
# keys the dashboard's Import flow already knows how to apply to the form.
PROFILE_FACTS_SCHEMA = obj({
    "summary": STR,
    "education": {"type": "array", "items": obj({"degree": STR, "school": STR, "year": STR})},
    "certifications": {"type": "array", "items": obj({"name": STR, "issuer": STR, "date": STR})},
    "skills": {"type": "array", "items": obj({"category": STR, "skills": STR_LIST})},
    "projects": {"type": "array", "items": obj({"name": STR, "tech": STR, "description": STR})},
    "experience": {"type": "array", "items": obj(
        {"title": STR, "company": STR, "dates": STR, "bullets": STR_LIST})},
})


def facts_to_suggestions(facts: dict) -> dict:
    """Convert schema output to the dashboard's suggestion shape (skills as a dict)."""
    out = dict(facts)
    out["skills"] = {s["category"]: s["skills"] for s in facts.get("skills", []) if s.get("skills")}
    return out
