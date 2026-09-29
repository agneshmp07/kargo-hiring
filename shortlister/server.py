"""Public web endpoints (run with: python -m shortlister server):

    /api/apply               careers form (role, CV upload, consent, optional WhatsApp opt-in)
    /api/privacy             privacy notice
    /api/webhooks/resend     delivery / bounce events from Resend (Svix-signed)
    /api/webhooks/calcom     booking events from Cal.com (X-Cal-Signature-256)
    /api/webhooks/calendly   booking events from Calendly (Calendly-Webhook-Signature)
    /api/healthz
    /api/...                 the JSON API for the Next.js app (webapi.py)

Everything lives under /api because that's the path Vercel routes to the Python function.
On Vercel, /apply and /privacy are rewritten here by vercel.json.

Every webhook is rejected unless its signature verifies with the matching secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import time

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from . import config, decisions, emails, intake, settings, store, versions, webapi

app = FastAPI(title="Kargo hiring API", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(webapi.router)

PUBLIC_REAL = ("/api/apply", "/apply", "/api/privacy", "/privacy", "/api/webhooks/")


class ModeMiddleware:
    """Pick the demo or the real product for each request. The visitor's choice lives in the
    kargo_mode cookie. The careers form and the webhooks belong to the real product; with only one
    product available there's nothing to choose."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from http.cookies import SimpleCookie

        modes = config.available_modes()
        raw = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"cookie"), "")
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # noqa: BLE001 - a malformed cookie header just means "no choice"
            pass
        chosen = jar[webapi.MODE_COOKIE].value if webapi.MODE_COOKIE in jar else None
        path = scope.get("path", "")
        if len(modes) == 1:
            mode = modes[0]
        elif chosen in modes:
            mode = chosen
        elif path.startswith(PUBLIC_REAL) and "real" in modes:
            mode = "real"
        else:
            mode = "none"  # nothing chosen yet: only the opening screen works
        with config.use_mode(mode):
            await self.app(scope, receive, send)


app.add_middleware(ModeMiddleware)

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
:root{{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e3e3de;--accent:#e4572e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141413;--fg:#f0efe9;--muted:#a3a39c;--card:#1f1f1d;--line:#34342f}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}}
main{{max-width:560px;margin:0 auto;padding:32px 16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:24px}}
label{{display:block;margin:16px 0 6px;font-weight:600}} small,.muted{{color:var(--muted)}}
select,input[type=file]{{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}}
.check{{display:flex;gap:10px;align-items:flex-start;font-weight:400}} .check input{{margin-top:4px}}
button{{margin-top:20px;width:100%;padding:12px;border:0;border-radius:8px;background:var(--accent);color:#fff;font-size:16px;font-weight:600}}
</style></head><body><main>{body}</main></body></html>"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=html.escape(title), body=body))


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/api/apply")


@app.get("/apply", include_in_schema=False)
def apply_alias():
    return RedirectResponse("/api/apply")


@app.get("/privacy", include_in_schema=False)
def privacy_alias():
    return RedirectResponse("/api/privacy")


@app.get("/api/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/privacy", response_class=HTMLResponse)
def privacy():
    text = html.escape(settings.privacy_notice()).replace("\n\n", "</p><p>")
    return _page("Privacy notice", f'<div class="card"><h1>How Kargo uses your data</h1><p>{text}</p></div>')


@app.get("/api/apply", response_class=HTMLResponse)
def apply_form():
    names = versions.role_names(versions.active())
    options = "".join(f'<option value="{html.escape(c)}">{html.escape(n)}</option>' for c, n in names.items())
    body = f"""<div class="card"><h1>Apply to Kargo</h1>
<p class="muted">We build software for freight forwarders and 3PLs in Mumbai. A person reviews every application.</p>
<form method="post" action="/api/apply" enctype="multipart/form-data">
<label for="role">Role</label><select id="role" name="role" required>{options}</select>
<label for="cv">Your CV</label><input id="cv" type="file" name="cv" required accept=".pdf,.docx,.doc,.txt,.rtf,.odt">
<small>PDF or Word, up to 10 MB.</small>
<label class="check"><input type="checkbox" name="consent" value="yes" required>
<span>I agree that Kargo may process my CV to assess this application, as described in the
<a href="/api/privacy" target="_blank">privacy notice</a>.</span></label>
<label class="check"><input type="checkbox" name="whatsapp" value="yes">
<span>You may also message me about interview scheduling on WhatsApp.</span></label>
<button type="submit">Send application</button></form></div>"""
    return _page("Apply to Kargo", body)


@app.post("/api/apply", response_class=HTMLResponse)
async def apply_submit(role: str = Form(...), cv: UploadFile = File(...), consent: str = Form(""),
                       whatsapp: str = Form("")):
    if consent != "yes":
        raise HTTPException(400, "Consent is required to process your application.")
    if role not in versions.role_names(versions.active()):
        raise HTTPException(400, "Unknown role.")
    data = await cv.read(intake.MAX_BYTES + 1)
    name, msg = intake.save_incoming(cv.filename or "cv", data, role, source="careers", consent=True,
                                     whatsapp_opt_in=whatsapp == "yes")
    if not name and "already received" not in msg:
        return _page("Please try again", f'<div class="card"><h1>That didn\'t work</h1><p>{html.escape(msg)}</p>'
                                         '<p><a href="/api/apply">Back to the form</a></p></div>')
    return _page("Thank you", '<div class="card"><h1>Thank you for applying</h1><p>We have your application. '
                              'A person at Kargo reviews every CV, and we will get back to you either way.</p></div>')


# ---------------------------------------------------------------- webhooks

def _log_event(source: str, event_type: str, ref: str | None, payload: dict) -> None:
    with store.connect() as conn:
        conn.execute("INSERT INTO webhook_events (source, event_type, ref, payload, ts) VALUES (?,?,?,?,?)",
                     (source, event_type, ref, json.dumps(payload)[:20000], store.now()))


def verify_svix(secret: str, headers, body: bytes, tolerance: int = 300) -> bool:
    msg_id, ts, sigs = headers.get("svix-id"), headers.get("svix-timestamp"), headers.get("svix-signature")
    if not (secret and msg_id and ts and sigs):
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
        key = base64.b64decode(secret.split("_", 1)[1] if secret.startswith("whsec_") else secret)
    except (ValueError, IndexError):
        return False
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return any(hmac.compare_digest(expected, s.split(",", 1)[-1]) for s in sigs.split())


def verify_hex_hmac(secret: str, signature: str | None, message: bytes) -> bool:
    if not (secret and signature):
        return False
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


@app.post("/api/webhooks/resend")
async def resend_webhook(request: Request):
    body = await request.body()
    if not verify_svix(config.env("RESEND_WEBHOOK_SECRET") or "", request.headers, body):
        raise HTTPException(401, "bad signature")
    from .resend_client import event_detail

    evt = json.loads(body)
    provider_id = (evt.get("data") or {}).get("email_id")
    _log_event("resend", evt.get("type", ""), provider_id, evt)
    if provider_id:
        emails.apply_provider_event(provider_id, evt.get("type", ""), event_detail(evt))
    return {"ok": True}


def _booking(cid_hint: str | None, email: str | None, start: str | None, ref: str | None, cancelled: bool,
             source: str) -> dict:
    cid = decisions.find_candidate_for_booking(cid_hint, email)
    if not cid:
        return {"ok": True, "matched": False}
    try:
        decisions.set_stage(cid, "invited" if cancelled else "scheduled", f"{source} webhook",
                            scheduled_for=None if cancelled else start, booking_ref=ref)
    except decisions.DecisionError:
        pass  # outcome already recorded; ignore late booking events
    return {"ok": True, "matched": True}


@app.post("/api/webhooks/calcom")
async def calcom_webhook(request: Request):
    body = await request.body()
    if not verify_hex_hmac(config.env("CALCOM_WEBHOOK_SECRET") or "", request.headers.get("x-cal-signature-256"), body):
        raise HTTPException(401, "bad signature")
    evt = json.loads(body)
    trig, p = evt.get("triggerEvent", ""), evt.get("payload") or {}
    _log_event("calcom", trig, p.get("uid"), evt)
    if trig not in ("BOOKING_CREATED", "BOOKING_RESCHEDULED", "BOOKING_CANCELLED"):
        return {"ok": True}
    attendee = (p.get("attendees") or [{}])[0].get("email")
    return _booking((p.get("metadata") or {}).get("candidate_id"), attendee, p.get("startTime"), p.get("uid"),
                    trig == "BOOKING_CANCELLED", "cal.com")


@app.post("/api/webhooks/calendly")
async def calendly_webhook(request: Request):
    body = await request.body()
    header = request.headers.get("calendly-webhook-signature", "")
    parts = dict(kv.split("=", 1) for kv in header.split(",") if "=" in kv)
    if not verify_hex_hmac(config.env("CALENDLY_WEBHOOK_SECRET") or "", parts.get("v1"),
                           f"{parts.get('t', '')}.".encode() + body):
        raise HTTPException(401, "bad signature")
    evt = json.loads(body)
    kind, p = evt.get("event", ""), evt.get("payload") or {}
    _log_event("calendly", kind, p.get("uri"), evt)
    if kind not in ("invitee.created", "invitee.canceled"):
        return {"ok": True}
    return _booking((p.get("tracking") or {}).get("utm_content"), p.get("email"),
                    (p.get("scheduled_event") or {}).get("start_time"), p.get("uri"),
                    kind == "invitee.canceled", "calendly")


def run(host: str = "0.0.0.0", port: int = 8600) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)
