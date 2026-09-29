"""Resend (https://resend.com) for outgoing email.

- Every send carries an Idempotency-Key derived from the email's row ID, so a retry, or two
  workers picking up the same email, can never send it twice (Resend keeps keys for 24 hours).
- A User-Agent header is always set (Resend rejects requests without one with a 403).
- 429 (rate limit) and 5xx get short backoff retries; other 4xx fail at once with Resend's message.
- Emails go out as HTML plus the plain-text original, with Reply-To and tags.
- The API key is read at call time from RESEND_API_KEY and never logged.
"""
from __future__ import annotations

import html
import os
import re
import time

from . import config

API = "https://api.resend.com"
USER_AGENT = "kargo-hiring/1.0"
TAG_SAFE = re.compile(r"[^A-Za-z0-9_-]")


class ResendError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _key() -> str:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        raise ResendError("RESEND_API_KEY is not set")
    return key


def _headers(idempotency_key: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json", "User-Agent": USER_AGENT}
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key[:256]
    return h


def _tag(value: str) -> str:
    return TAG_SAFE.sub("_", str(value))[:256] or "none"


def text_to_html(text: str) -> str:
    """Plain, readable HTML from the plain-text template: paragraphs, line breaks and links."""
    def para(block: str) -> str:
        esc = html.escape(block.strip())
        esc = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#d64e2b">\1</a>', esc)
        return f'<p style="margin:0 0 14px">{esc.replace(chr(10), "<br>")}</p>'

    body = "".join(para(b) for b in re.split(r"\n\s*\n", text.strip()) if b.strip())
    return ('<!doctype html><html><body style="margin:0;background:#f7f7f4">'
            '<div style="max-width:560px;margin:0 auto;padding:28px 20px;font:15px/1.55 -apple-system,Segoe UI,'
            'Roboto,Helvetica,Arial,sans-serif;color:#1c1c1a">'
            f'{body}</div></body></html>')


def send(*, to: str, subject: str, text: str, idempotency_key: str | None = None, tags: dict | None = None,
         reply_to: str | None = None, session=None, sleep=time.sleep) -> str:
    """Send one email. Returns Resend's email id. Raises ResendError on failure."""
    import requests

    http = session or requests
    payload = {"from": config.from_email(), "to": [to], "subject": subject, "text": text, "html": text_to_html(text)}
    reply_to = reply_to or config.env("REPLY_TO")
    if reply_to:
        payload["reply_to"] = reply_to
    if tags:
        payload["tags"] = [{"name": _tag(k), "value": _tag(v)} for k, v in tags.items() if v]
    delays = [1.0, 3.0]  # backoff for 429 / 5xx; the caller adds its own single retry on top
    while True:
        resp = http.post(f"{API}/emails", headers=_headers(idempotency_key), json=payload, timeout=20)
        if resp.status_code < 300:
            return (resp.json() or {}).get("id", "")
        if (resp.status_code == 429 or resp.status_code >= 500) and delays:
            wait = resp.headers.get("retry-after")
            sleep(float(wait) if wait and wait.replace(".", "").isdigit() else delays[0])
            delays.pop(0)
            continue
        try:
            msg = resp.json().get("message") or resp.text
        except ValueError:
            msg = resp.text
        raise ResendError(f"Resend HTTP {resp.status_code}: {str(msg)[:200]}", resp.status_code)


def domain_status(session=None) -> dict:
    """Is the FROM_EMAIL domain verified in Resend? Uses GET /domains (needs a full-access key;
    a sending-only key can still send but can't read domains)."""
    import requests

    sender = config.from_email()
    m = re.search(r"@([\w.-]+)", sender)
    domain = m.group(1).lower() if m else None
    if not os.environ.get("RESEND_API_KEY", "").strip():
        return {"ok": False, "state": "no_key", "domain": domain, "message": "RESEND_API_KEY is not set."}
    if domain == "resend.dev":
        return {"ok": True, "state": "test_domain", "domain": domain,
                "message": "resend.dev is Resend's test sender: it only delivers to your own account's address, "
                           "so keep TEST_RECIPIENT set to that address."}
    try:
        resp = (session or requests).get(f"{API}/domains", headers=_headers(), timeout=15)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "state": "error", "domain": domain, "message": f"Couldn't reach Resend: {type(exc).__name__}"}
    if resp.status_code in (401, 403):
        return {"ok": None, "state": "restricted_key", "domain": domain,
                "message": "This key can send but can't read domains (a sending-only key). Sending may still work."}
    if resp.status_code >= 300:
        return {"ok": False, "state": "error", "domain": domain, "message": f"Resend HTTP {resp.status_code}"}
    rows = (resp.json() or {}).get("data", [])
    match = next((d for d in rows if domain and (domain == d.get("name") or domain.endswith("." + d.get("name", "")))),
                 None)
    if domain == "resend.dev":
        return {"ok": True, "state": "test_domain", "domain": domain,
                "message": "resend.dev is Resend's test sender: it only delivers to your own account's address."}
    if not match:
        return {"ok": False, "state": "not_added", "domain": domain,
                "message": f"{domain} isn't added in Resend. Add it under Domains and set the DNS records."}
    verified = match.get("status") == "verified"
    return {"ok": verified, "state": match.get("status"), "domain": domain, "region": match.get("region"),
            "message": "Verified: ready to send." if verified else
            f"Status '{match.get('status')}': finish the DNS records in Resend, then click Verify."}


# Webhook event -> email status. Later events never overwrite a worse outcome (see RANK).
EVENT_STATUS = {
    "email.delivered": "delivered", "email.bounced": "bounced", "email.complained": "complained",
    "email.failed": "failed", "email.suppressed": "suppressed",
}
RANK = {"scheduled": 0, "sent": 1, "dry_run": 1, "delivered": 2, "failed": 3, "suppressed": 3, "bounced": 4,
        "complained": 5}


def new_status(current: str, event: str) -> str:
    target = EVENT_STATUS.get(event)
    if not target or current == "cancelled":
        return current
    return target if RANK.get(target, 0) >= RANK.get(current, 0) else current


def event_detail(evt: dict) -> str | None:
    data = evt.get("data") or {}
    b = data.get("bounce") or {}
    if b:
        return f"{b.get('type', '')} {b.get('subType', '')}: {b.get('message', '')}".strip()[:300]
    f = data.get("failed") or {}
    return (f.get("reason") or None) if isinstance(f, dict) else None
