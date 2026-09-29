"""Google Gemini as the classifier (Interactions REST API, no extra SDK needed).

It gets exactly the same redacted payload the Claude path builds (llm.build_payload), so the
redaction test still covers it: system prompt with the verbatim anchors, the redacted CV, and
the strict JSON schema. The output then goes through the same validation, evidence rule and
policy scrub. Code, not the model, computes every score.

Data protection: on Gemini's free tier Google may use prompts to improve its products and
human reviewers may read them, and its terms say not to send personal information there.
So real CVs are only sent when GEMINI_PAID_TIER=true (a billing-enabled key). The demo, with
fictional CVs, may use the free tier.
"""
from __future__ import annotations

import json
import time

from . import config

API = "https://generativelanguage.googleapis.com/v1beta/interactions"
USER_AGENT = "kargo-hiring/1.0"
DEFAULT_MODEL = "gemini-3.8-flash"


class GeminiError(RuntimeError):
    pass


def api_key() -> str | None:
    return config.env("GEMINI_API_KEY") or config.env("GOOGLE_API_KEY")


def check_allowed() -> None:
    """Refuse to send real candidates' CVs to Gemini's free tier."""
    if config.is_demo():
        return
    if not config.env_bool("GEMINI_PAID_TIER", False):
        raise GeminiError(
            "Gemini is set as the AI, but GEMINI_PAID_TIER is not 'true'. On Gemini's free tier Google may use "
            "what you send to improve its products and people may read it, so real CVs are not sent there. "
            "Enable billing on your Google AI Studio project and set GEMINI_PAID_TIER=true (or use the demo).")


def to_request(payload: dict) -> dict:
    """Translate the provider-neutral payload built by llm.build_payload into a Gemini request."""
    system = "".join(b["text"] for b in payload["system"]) if isinstance(payload["system"], list) else payload["system"]
    user = payload["messages"][0]["content"]
    return {
        "model": payload["model"],
        "system_instruction": system,
        "input": user,
        "generation_config": {"temperature": 0},
        "response_format": {"type": "text", "mime_type": "application/json",
                            "schema": payload["output_config"]["format"]["schema"]},
        "store": False,  # don't keep the interaction on Google's side
    }


def output_text(resp: dict) -> str:
    if resp.get("status") in ("failed", "cancelled", "incomplete"):
        raise GeminiError(f"Gemini returned status '{resp.get('status')}'")
    for k in ("output_text", "outputText"):
        if resp.get(k):
            return resp[k]
    parts = []
    for step in resp.get("steps") or resp.get("outputs") or []:
        if step.get("type") in (None, "model_output", "text"):
            for c in step.get("content") or ([step] if step.get("text") else []):
                if c.get("type", "text") == "text" and c.get("text"):
                    parts.append(c["text"])
    if not parts:
        raise GeminiError("Gemini returned no text")
    return "".join(parts)


def usage(resp: dict) -> dict:
    u = resp.get("usage") or {}
    return {"input": u.get("total_input_tokens", 0) or 0,
            "output": (u.get("total_output_tokens", 0) or 0) + (u.get("total_thought_tokens", 0) or 0),
            "cache_read": u.get("total_cached_tokens", 0) or 0}


def call(payload: dict, session=None, sleep=time.sleep) -> tuple[str, dict]:
    import requests

    key = api_key()
    if not key:
        raise GeminiError("GEMINI_API_KEY is not set")
    http = session or requests
    headers = {"x-goog-api-key": key, "Content-Type": "application/json", "User-Agent": USER_AGENT}
    delays = [2.0, 5.0]
    while True:
        resp = http.post(API, headers=headers, json=to_request(payload), timeout=120)
        if resp.status_code < 300:
            data = resp.json()
            return output_text(data), usage(data)
        if (resp.status_code == 429 or resp.status_code >= 500) and delays:
            sleep(delays.pop(0))
            continue
        try:
            msg = (resp.json().get("error") or {}).get("message") or resp.text
        except ValueError:
            msg = resp.text
        raise GeminiError(f"Gemini HTTP {resp.status_code}: {str(msg)[:200]}")


def classify(payload: dict, params: dict | None = None, session=None, sleep=time.sleep):
    """Same contract as llm.classify: one retry on invalid output. Returns (obj, error, usage)."""
    from . import llm

    check_allowed()
    last_err, total = None, {}
    for attempt in (1, 2):
        try:
            text, u = call(payload, session=session, sleep=sleep)
            total = {k: total.get(k, 0) + u.get(k, 0) for k in set(total) | set(u)}
            obj, err = llm._parse(text, params)
            if obj is not None:
                return obj, None, total
            last_err = f"attempt {attempt}: {err}"
        except GeminiError as exc:
            last_err = f"attempt {attempt}: {exc}"
            if "GEMINI_PAID_TIER" in str(exc) or "not set" in str(exc):
                break
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = f"attempt {attempt}: {type(exc).__name__}: {exc}"
    return None, last_err, total
