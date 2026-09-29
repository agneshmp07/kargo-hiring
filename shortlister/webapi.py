"""JSON API for the Next.js app (all routes under /api). Runs as a Vercel Python function.

Security:
- Session: HttpOnly, SameSite=Lax cookie holding an HMAC-signed username + expiry (SESSION_SECRET).
- CSRF: every state-changing request must carry the header X-Requested-With: kargo (browsers can't
  add custom headers cross-site without a CORS preflight, which this API never allows).
- Permissions are checked here, server-side, with the same rules as the Streamlit app.
- /api/cron/tick requires Authorization: Bearer CRON_SECRET (Vercel Cron sends it).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from . import (analytics, auth, automation, config, cvstore, decisions, emails, intake, pipeline, privacy, settings,
               store, vault, versions)
from .pipeline import primary_role

router = APIRouter(prefix="/api")
COOKIE = "kargo_session"
SESSION_DAYS = 7


# ---------------------------------------------------------------- sessions

def _secret() -> bytes:
    env = config.env("SESSION_SECRET")
    if env:
        return env.encode()
    if config.on_vercel() and not config.is_demo():
        raise HTTPException(500, "SESSION_SECRET is not set")
    with store.connect() as conn:  # local / demo: a random secret kept in the database
        s = store.get_setting(conn, "_state.session_secret")
        if not s:
            s = secrets.token_hex(32)
            store.put_setting(conn, "_state.session_secret", s, "system")
    return s.encode()


def _mode() -> str:
    return config.current_mode() or ("demo" if config.is_demo() else "real")


def make_token(username: str) -> str:
    """Signed 'mode|username|expiry'. A demo sign-in can never be used on the real product."""
    exp = int(time.time()) + SESSION_DAYS * 86400
    body = f"{_mode()}|{username}|{exp}".encode()
    sig = hmac.new(_secret(), body, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(body).decode() + "." + sig


def read_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    b64, sig = token.rsplit(".", 1)
    try:
        body = base64.urlsafe_b64decode(b64.encode())
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(hmac.new(_secret(), body, hashlib.sha256).hexdigest(), sig):
        return None
    parts = body.decode().split("|")
    if len(parts) != 3:
        return None
    mode, username, exp = parts
    if mode != _mode():
        return None
    return username if exp.isdigit() and int(exp) > time.time() else None


def _set_cookie(resp: Response, username: str) -> None:
    resp.set_cookie(COOKIE, make_token(username), max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=config.on_vercel(), path="/")


def current_user(request: Request) -> dict | None:
    username = read_token(request.cookies.get(COOKIE))
    if not username:
        return None
    u = auth.get_user(username)
    return u if u and u["active"] else None


def need(perm: str):
    def dep(request: Request) -> dict:
        u = current_user(request)
        if not u:
            raise HTTPException(401, "please sign in")
        if not auth.can(u, perm):
            raise HTTPException(403, "you don't have access to this")
        if request.method != "GET" and request.headers.get("x-requested-with") != "kargo":
            raise HTTPException(403, "missing request header")
        return u
    return dep


def _ok(**kw):
    return {"ok": True, **kw}


def _err(exc: Exception, code: int = 400):
    raise HTTPException(code, str(exc))


# ---------------------------------------------------------------- auth

MODE_COOKIE = "kargo_mode"


def _chosen() -> str | None:
    """The product this request is for, or None when the visitor hasn't picked one yet."""
    return config.current_mode() if config.current_mode() in config.available_modes() else None


@router.get("/auth/state")
def auth_state():
    modes = config.available_modes()
    mode = _chosen()
    out = {"modes": modes, "mode": mode, "demo": mode == "demo", "has_users": None, "demo_users": [],
           "setup": None}
    if mode is None:
        return out  # opening screen: choose the demo or the real product (no database touched)
    if mode == "demo":
        auth.seed_demo_users()
        out["demo_users"] = [{"username": u["username"], "display_name": u["display_name"], "role": u["role"],
                              "role_label": auth.ROLE_LABELS[u["role"]]} for u in auth.users(active_only=True)]
    out["has_users"] = auth.has_users()
    if not out["has_users"] and mode == "real":
        out["setup"] = "code" if config.env("SETUP_CODE") else ("cli" if config.on_vercel() else "open")
    return out


@router.post("/auth/mode")
async def choose_mode(request: Request):
    """Opening-screen choice: 'demo' or 'real' (or null to go back to the choice)."""
    b = await request.json()
    mode = b.get("mode")
    if mode is not None and mode not in config.available_modes():
        raise HTTPException(400, "that product isn't available here")
    resp = JSONResponse(_ok(mode=mode))
    resp.delete_cookie(COOKIE, path="/")  # a new choice always starts signed out
    if mode is None:
        resp.delete_cookie(MODE_COOKIE, path="/")
    else:
        resp.set_cookie(MODE_COOKIE, mode, max_age=30 * 86400, httponly=True, samesite="lax",
                        secure=config.on_vercel(), path="/")
    return resp


@router.get("/auth/me")
def me(request: Request):
    u = current_user(request)
    if not u:
        raise HTTPException(401, "please sign in")
    perms = sorted(p for p in ("view", "decide", "upload", "comment", "review", "scorecard", "schedule", "calibrate",
                               "admin") if auth.can(u, p))
    return {"user": {k: u[k] for k in ("username", "display_name", "role", "email")},
            "role_label": auth.ROLE_LABELS.get(u["role"], u["role"]), "perms": perms,
            "mode": {"demo": config.is_demo(), "modes": config.available_modes(),
                     "dry_run": config.dry_run(), "test_recipient": bool(config.test_recipient()),
                     "api_ready": config.api_ready(), "model": config.model(), "provider": config.llm_provider(),
                     "database": store.backend(),
                     "storage": config.storage_mode()}}


def _need_mode():
    if _chosen() is None:
        raise HTTPException(409, "choose the demo or the real product first")


@router.post("/auth/login")
async def login(request: Request):
    _need_mode()
    body = await request.json()
    u = auth.authenticate(body.get("username", ""), body.get("password", ""))
    if not u:
        raise HTTPException(401, "That username and password don't match.")
    resp = JSONResponse(_ok())
    _set_cookie(resp, u["username"])
    return resp


@router.post("/auth/demo-login")
async def demo_login(request: Request):
    _need_mode()
    if not config.is_demo():
        raise HTTPException(404)
    body = await request.json()
    u = auth.get_user(body.get("username", ""))
    if not u:
        raise HTTPException(404, "unknown demo user")
    resp = JSONResponse(_ok())
    _set_cookie(resp, u["username"])
    return resp


@router.post("/auth/setup")
async def setup(request: Request):
    """First (founder) account for the real product. On a public deployment this needs SETUP_CODE,
    so the first stranger to open the site can't make themselves the founder."""
    _need_mode()
    if auth.has_users():
        raise HTTPException(409, "already set up")
    b = await request.json()
    code = config.env("SETUP_CODE")
    if code:
        if not hmac.compare_digest(str(b.get("setup_code", "")), code):
            raise HTTPException(403, "That setup code isn't right.")
    elif config.on_vercel() and not config.is_demo():
        raise HTTPException(403, 'Create the first account from your computer: python -m shortlister adduser '
                                 '<username> --name "Your Name" --role founder --email you@example.com')
    try:
        auth.create_user(b.get("username", ""), b.get("name", ""), "founder", b.get("password", ""), b.get("email", ""),
                         by="setup")
    except ValueError as exc:
        _err(exc)
    resp = JSONResponse(_ok())
    _set_cookie(resp, b["username"].strip().lower())
    return resp


@router.post("/auth/logout")
def logout():
    resp = JSONResponse(_ok())
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- board

def _card(c: dict, ctx: dict) -> dict:
    obj = c["llm_json"] or {}
    dec = ctx["latest"].get(c["id"])
    email = ctx["email_by_decision"].get(dec["id"]) if dec else None
    revealed = bool(dec and dec["decision"] == "Advance")
    return {
        "id": c["id"], "name": (vault.get(c["id"]).get("name") or "name not found") if revealed else None,
        "applied_role": c["applied_role"], "primary_role": primary_role(c), "better_fit": c["better_fit"],
        "results": c["results_json"], "rationale": obj.get("rationale", ""), "probes": obj.get("probes", []),
        "pm_years": obj.get("pm_years"), "pm_years_working": obj.get("pm_years_working", ""),
        "city": obj.get("city", "unknown"), "open_to_relocate": obj.get("open_to_relocate", "unknown"),
        "layer_a": obj.get("layer_a", {}), "layer_b": obj.get("layer_b", {}),
        "confidence": c["confidence"], "low_conf_reasons": c["low_conf_reasons"] or [],
        "evidence_flags": c["evidence_flags"] or [], "duplicate_of": c["duplicate_of"], "source": c["source"],
        "backlog": bool(c["backlog"]), "received_at": c["received_at"],
        "decision": dec and {k: dec[k] for k in ("id", "decision", "role", "ts", "decided_by")},
        "email_status": email and email["status"], "email_send_after": email and email["send_after"],
        "undoable": ctx["undoable"].get(c["id"], False),
        "stage": ctx["stages"].get(c["id"]),
        "comments": ctx["comments"].get(c["id"], []), "reviews": ctx["reviews"].get(c["id"], []),
        "hold_days": (ctx["reminders"].get(c["id"]) or {}).get("days"),
    }


def _context() -> dict:
    with store.connect() as conn:
        cands = store.all_candidates(conn)
        latest = {}
        for c in cands:
            d = store.latest_decision(conn, c["id"])
            latest[c["id"]] = dict(d) if d else None
        msgs = store.emails(conn)
        spots = store.rows(conn, "SELECT * FROM spot_checks ORDER BY id DESC")
        stages = {s["candidate_id"]: s for s in store.rows(conn, "SELECT * FROM stages")}
        comments, reviews = {}, {}
        for cm in store.rows(conn, "SELECT * FROM comments ORDER BY id"):
            comments.setdefault(cm["candidate_id"], []).append(cm)
        for rv in store.rows(conn, "SELECT * FROM reviews ORDER BY id DESC"):
            reviews.setdefault(rv["candidate_id"], []).append(rv)
        undoable = {cid: decisions.undoable(conn, d) for cid, d in latest.items() if d}
    email_by_decision = {}
    for e in sorted(msgs, key=lambda e: e["id"]):
        if e["decision_id"] and e["channel"] == "email" and e["kind"] in ("invite", "rejection"):
            email_by_decision.setdefault(e["decision_id"], e)
    return {"cands": cands, "latest": latest, "emails": msgs, "email_by_decision": email_by_decision,
            "spots": spots, "stages": stages, "comments": comments, "reviews": reviews, "undoable": undoable,
            "reminders": {r["candidate_id"]: r for r in decisions.hold_reminders()}}


@router.get("/board")
def board(u=Depends(need("view"))):
    try:
        emails.send_due()  # anything whose undo window has passed goes out now
    except Exception:  # noqa: BLE001 - never block the board on delivery problems
        pass
    ctx = _context()
    params = versions.active()
    roles = versions.role_codes(params)
    cards = [_card(c, ctx) for c in ctx["cands"]]
    return {
        "roles": roles, "role_names": versions.role_names(params), "cards": cards,
        "spots": ctx["spots"], "bulk": {r: decisions.bulk_pass_candidates(r) for r in roles} if auth.can(u, "decide") else {},
        "users": [{"username": x["username"], "display_name": x["display_name"], "role": x["role"],
                   "can_review": auth.can(x, "review")} for x in auth.users(active_only=True)],
        "undo_minutes": settings.get("undo_minutes"),
    }


@router.post("/decisions")
async def decide(request: Request, u=Depends(need("decide"))):
    b = await request.json()
    try:
        out = decisions.record(b["candidate_id"], b["role"], b["decision"], by=u["username"])
    except (decisions.DecisionError, KeyError) as exc:
        _err(exc)
    name = vault.get(b["candidate_id"]).get("name") if b["decision"] == "Advance" else None
    return _ok(decision_id=out["decision_id"], email_status=out["email"] and out["email"]["status"], name=name)


@router.post("/decisions/{decision_id}/undo")
def undo(decision_id: int, u=Depends(need("decide"))):
    try:
        decisions.undo(decision_id, by=u["username"])
    except decisions.DecisionError as exc:
        _err(exc)
    return _ok()


@router.post("/bulk-pass")
async def bulk_pass(request: Request, u=Depends(need("decide"))):
    b = await request.json()
    return _ok(count=len(decisions.bulk_pass(b["role"], by=u["username"])))


@router.post("/spot-checks/{spot_id}")
async def spot(spot_id: int, request: Request, u=Depends(need("decide"))):
    b = await request.json()
    try:
        decisions.spot_check_verdict(spot_id, b["verdict"], by=u["username"])
    except decisions.DecisionError as exc:
        _err(exc)
    return _ok()


@router.post("/comments")
async def comment(request: Request, u=Depends(need("comment"))):
    b = await request.json()
    try:
        decisions.add_comment(b["candidate_id"], u["username"], b.get("body", ""))
    except decisions.DecisionError as exc:
        _err(exc)
    return _ok()


@router.post("/reviews")
async def ask_review(request: Request, u=Depends(need("comment"))):
    b = await request.json()
    try:
        decisions.request_review(b["candidate_id"], b["role"], u["username"], b["assignee"])
    except decisions.DecisionError as exc:
        _err(exc)
    return _ok()


@router.get("/reviews/mine")
def my_reviews(u=Depends(need("review"))):
    ctx = _context()
    by_id = {c["id"]: c for c in ctx["cands"]}
    mine = [dict(r, card=_card(by_id[r["candidate_id"]], ctx))
            for r in decisions.reviews(assignee=u["username"], open_only=True) if r["candidate_id"] in by_id]
    asked = [r for r in decisions.reviews() if r["requested_by"] == u["username"]]
    params = versions.active()
    return {"mine": mine, "asked": asked, "role_names": versions.role_names(params)}


@router.post("/reviews/{review_id}/answer")
async def answer_review(review_id: int, request: Request, u=Depends(need("review"))):
    b = await request.json()
    try:
        decisions.answer_review(review_id, u["username"], b.get("opinion", ""), b.get("note", ""))
    except decisions.DecisionError as exc:
        _err(exc)
    return _ok()


# ---------------------------------------------------------------- CVs in

def _standin() -> bool:
    return config.is_demo() and not config.api_ready()


@router.get("/cvs/pending")
def pending(u=Depends(need("view"))):
    params = versions.active()
    block = None
    if (config.api_ready() and config.llm_provider() == "gemini" and not config.is_demo()
            and not config.env_bool("GEMINI_PAID_TIER", False)):
        block = ("Scoring is paused: this Gemini key is on the free tier, where Google may use the data, so real "
                 "CVs aren't sent. Enable billing and set GEMINI_PAID_TIER=true, or use a Claude key.")
    return {"pending": pipeline.pending_files(), "can_score": (config.api_ready() or _standin()) and not block,
            "score_block": block,
            "standin": _standin(), "role_names": versions.role_names(params),
            "inbox": intake.inbox_configured(), "careers_url": f"{config.public_base_url()}/apply",
            "demo": config.is_demo()}


@router.post("/cvs/upload")
async def upload(request: Request, role: str = Form(""), files: list[UploadFile] = File(...),
                 u=Depends(need("upload"))):
    saved, notes = [], []
    for f in files:
        data = await f.read(intake.MAX_BYTES + 1)
        name, note = intake.save_incoming(f.filename or "cv", data, role, source="upload", uploaded_by=u["username"])
        (saved if name else notes).append(name or note)
    return _ok(saved=saved, notes=notes)


@router.post("/cvs/score-next")
def score_next(u=Depends(need("upload"))):
    """Score one waiting CV. The page calls this repeatedly and shows progress; one CV per request
    keeps each request well inside Vercel's time limit."""
    if not (config.api_ready() or _standin()):
        raise HTTPException(400, "Add ANTHROPIC_API_KEY to score CVs.")
    kwargs = {"limit": 1, "log": lambda *_: None}
    if _standin():
        from .demo import keyword_classifier

        kwargs["classifier"] = keyword_classifier
    try:
        s = pipeline.run_batch(**kwargs)
    except Exception as exc:  # noqa: BLE001 - e.g. the Gemini free-tier guard, or an API outage
        raise HTTPException(400, str(exc)[:400])
    return _ok(scored=s["scored_ids"], remaining=s["remaining"], parse_failures=s["parse_failures"],
               cost_usd=s["cost_usd"])


@router.get("/demo/samples.zip")
def demo_samples(u=Depends(need("view"))):
    from .demo import samples_zip

    return Response(samples_zip(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="kargo-sample-cvs.zip"'})


@router.post("/demo/reset")
def demo_reset(u=Depends(need("view"))):
    if not config.is_demo():
        raise HTTPException(404)
    from . import demo

    demo.reset(log=lambda *_: None)
    return _ok()


# ---------------------------------------------------------------- interviews

@router.get("/interviews")
def interviews(u=Depends(need("view"))):
    ctx = _context()
    by_id = {c["id"]: c for c in ctx["cands"]}
    rows = []
    for s in ctx["stages"].values():
        c = by_id.get(s["candidate_id"])
        if c:
            rows.append({**s, "card": _card(c, ctx), "scorecards": decisions.scorecards(c["id"])})
    params = versions.active()
    return {"rows": rows, "stage_labels": decisions.STAGES, "role_names": versions.role_names(params)}


@router.post("/interviews/{cid}/stage")
async def set_stage(cid: str, request: Request, u=Depends(need("view"))):
    b = await request.json()
    stage = b.get("stage")
    perm = "decide" if stage in decisions.OUTCOME_STAGES else "schedule"
    if not auth.can(u, perm):
        raise HTTPException(403, "you don't have access to this")
    if request.headers.get("x-requested-with") != "kargo":
        raise HTTPException(403, "missing request header")
    try:
        decisions.set_stage(cid, stage, u["username"], scheduled_for=b.get("scheduled_for"))
    except decisions.DecisionError as exc:
        _err(exc)
    return _ok()


@router.post("/interviews/{cid}/scorecard")
async def scorecard(cid: str, request: Request, u=Depends(need("scorecard"))):
    b = await request.json()
    try:
        decisions.add_scorecard(cid, u["username"], b.get("ratings", {}), b.get("recommendation", ""),
                                b.get("notes", ""))
    except decisions.DecisionError as exc:
        _err(exc)
    return _ok()


# ---------------------------------------------------------------- calibrate & analytics

@router.get("/calibrate")
def calibrate(u=Depends(need("calibrate"))):
    q = analytics.calibration_queue(u["username"], n=10)
    nxt = None
    if q:
        c = q[0]
        nxt = {"id": c["id"], "role": primary_role(c), "text": c["redacted_text"]}
    params = versions.active()
    return {"next": nxt, "mine": analytics.calibration_summary(u["username"]),
            "team": analytics.calibration_summary(), "role_names": versions.role_names(params)}


@router.post("/calibrate")
async def rate(request: Request, u=Depends(need("calibrate"))):
    b = await request.json()
    try:
        analytics.rate(b["candidate_id"], u["username"], b["role"], b["rating"])
    except (ValueError, KeyError) as exc:
        _err(exc)
    return _ok()


@router.get("/analytics")
def analytics_view(role: str | None = None, u=Depends(need("view"))):
    params = versions.active()
    return {"funnel": analytics.funnel(role or None), "speed": analytics.time_to_decision(),
            "agreement": analytics.agreement(), "outcomes": analytics.outcomes_by_band(),
            "sources": analytics.source_quality(), "fairness": analytics.fairness_by_city(),
            "spend": analytics.spend(), "roles": versions.role_codes(params), "role_names": versions.role_names(params)}


@router.get("/analytics/report.pdf")
def report(u=Depends(need("view"))):
    return Response(analytics.report_pdf(), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="kargo-hiring-report.pdf"'})


@router.get("/analytics/training.csv")
def training(u=Depends(need("view"))):
    return Response(analytics.training_export_csv(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="kargo-training-data.csv"'})


# ---------------------------------------------------------------- history

@router.get("/history")
def history(u=Depends(need("view"))):
    with store.connect() as conn:
        decs = store.rows(conn, "SELECT * FROM decisions ORDER BY id DESC")
        msgs = store.rows(conn, "SELECT id, decision_id, candidate_id, kind, channel, purpose, to_addr, subject, "
                                "status, attempts, provider_event, error, send_after, updated_at FROM emails "
                                "ORDER BY id DESC")
        log = store.rows(conn, "SELECT ts, event, data FROM audit_log ORDER BY id DESC LIMIT 300")
    advanced = {d["candidate_id"] for d in decs if d["decision"] == "Advance" and not d["undone_at"]}
    for d in decs:
        d["name"] = vault.get(d["candidate_id"]).get("name", "") if d["candidate_id"] in advanced else ""
        d["floors"] = [a["rule"] for a in json.loads(d["floors"] or "[]")]
    for m in msgs:  # recipients are shown only for candidates who were invited, or for team mail
        if m["candidate_id"] and m["candidate_id"] not in advanced:
            m["to_addr"] = "(hidden)"
    return {"decisions": decs, "messages": msgs, "log": log}


@router.post("/messages/{email_id}/retry")
def retry(email_id: int, u=Depends(need("decide"))):
    return _ok(status=emails.deliver(email_id)["status"])


@router.get("/messages/{email_id}")
def message(email_id: int, u=Depends(need("view"))):
    with store.connect() as conn:
        m = store.one(conn, "SELECT id, candidate_id, kind, channel, subject, body, status FROM emails WHERE id = ?",
                      (email_id,))
    if not m:
        raise HTTPException(404)
    if m["candidate_id"]:  # names stay hidden unless the candidate was invited
        with store.connect() as conn:
            invited = conn.execute("SELECT 1 FROM decisions WHERE candidate_id = ? AND decision = 'Advance' "
                                   "AND undone_at IS NULL", (m["candidate_id"],)).fetchone()
        if not invited:
            name = vault.get(m["candidate_id"]).get("name") or ""
            import re

            for part in sorted({name, *name.split()} - {""}, key=len, reverse=True):
                m["body"] = re.sub(rf"\b{re.escape(part)}\b", "[name]", m["body"], flags=re.I)
    return m


# ---------------------------------------------------------------- settings (admin)

INTEGRATIONS = [
    ("Anthropic API (Claude scoring)", "ANTHROPIC_API_KEY"), ("Gemini API (Gemini scoring)", "GEMINI_API_KEY"),
    ("Gemini paid tier confirmed", "GEMINI_PAID_TIER"), ("Neon database", "DATABASE_URL"),
    ("Separate vault database", "VAULT_DATABASE_URL"), ("Vault encryption", "VAULT_KEY"),
    ("Session secret", "SESSION_SECRET"), ("Cron secret", "CRON_SECRET"),
    ("Resend (email)", "RESEND_API_KEY"), ("Sender address", "FROM_EMAIL"), ("Reply-to address", "REPLY_TO"),
    ("Resend webhooks", "RESEND_WEBHOOK_SECRET"),
    ("Scheduling link", "SCHEDULING_LINK"), ("Cal.com webhooks", "CALCOM_WEBHOOK_SECRET"),
    ("Calendly webhooks", "CALENDLY_WEBHOOK_SECRET"), ("WhatsApp (Twilio)", "TWILIO_AUTH_TOKEN"),
    ("Slack digest", "SLACK_WEBHOOK_URL"), ("Hiring inbox", "HIRING_IMAP_HOST"), ("Public address", "PUBLIC_BASE_URL"),
]


@router.get("/settings")
def get_settings(u=Depends(need("admin"))):
    params = versions.active()
    return {
        "settings": settings.all_settings(), "users": auth.users(), "role_labels": auth.ROLE_LABELS,
        "params": params, "history": versions.history(),
        "templates": emails.templates(), "placeholders": sorted(emails.PLACEHOLDERS),
        "layer_a_points": __import__("shortlister.scoring", fromlist=["x"]).LAYER_A_POINTS,
        "integrations": [{"label": l, "var": v, "set": bool(config.env(v))} for l, v in INTEGRATIONS],
        "vault": {"encrypted": vault.is_encrypted(), "location": store.vault_location()},
        "mode": {"demo": config.is_demo(), "dry_run": config.dry_run(), "storage": config.storage_mode(),
                 "database": store.backend()},
        "privacy_preview": settings.privacy_notice(),
    }


@router.post("/settings")
async def put_settings(request: Request, u=Depends(need("admin"))):
    b = await request.json()
    try:
        for k, v in b.items():
            if settings.get(k) != v:
                settings.put(k, v, u["username"])
    except KeyError as exc:
        _err(exc)
    return _ok()


@router.post("/users")
async def add_user(request: Request, u=Depends(need("admin"))):
    b = await request.json()
    try:
        auth.create_user(b.get("username", ""), b.get("name", ""), b.get("role", "viewer"),
                         None if config.is_demo() else b.get("password", ""), b.get("email", ""), by=u["username"])
    except ValueError as exc:
        _err(exc)
    return _ok()


@router.patch("/users/{username}")
async def edit_user(username: str, request: Request, u=Depends(need("admin"))):
    b = await request.json()
    if username == u["username"] and (b.get("active") is False or b.get("role") not in (None, "founder")):
        raise HTTPException(400, "you can't remove your own admin access")
    try:
        auth.update_user(username, role=b.get("role"), active=b.get("active"), by=u["username"])
        if b.get("password"):
            auth.set_password(username, b["password"], u["username"])
    except ValueError as exc:
        _err(exc)
    return _ok()


@router.post("/versions")
async def publish(request: Request, u=Depends(need("admin"))):
    b = await request.json()
    try:
        v = versions.publish(b["params"], b.get("note", ""), u["username"])
    except (ValueError, KeyError) as exc:
        _err(exc)
    return _ok(version=v)


@router.post("/versions/validate")
async def validate_version(request: Request, u=Depends(need("admin"))):
    b = await request.json()
    return {"errors": versions.validate(b.get("params", {}))}


@router.post("/versions/{version}/activate")
def activate(version: int, u=Depends(need("admin"))):
    try:
        versions.activate(version, u["username"])
    except ValueError as exc:
        _err(exc)
    return _ok()


@router.post("/recalculate")
def recalc(u=Depends(need("admin"))):
    return _ok(**versions.recalculate_all(u["username"]))


@router.post("/templates")
async def save_template(request: Request, u=Depends(need("admin"))):
    b = await request.json()
    try:
        emails.save_template(b["kind"], b.get("role", "*"), b["subject"], b["body"], u["username"])
    except (ValueError, KeyError) as exc:
        _err(exc)
    return _ok()


@router.post("/templates/check")
async def check_template(request: Request, u=Depends(need("admin"))):
    b = await request.json()
    errs = emails.validate_template(b.get("subject", ""), b.get("body", ""))
    preview = None
    if not errs:
        try:
            role = None if b.get("role", "*") == "*" else b.get("role")
            fields = {"first_name": "Asha", "role_name": versions.role_names(versions.active()).get(role, "the role"),
                      "scheduling_link": "https://cal.com/kargo/interview?metadata[candidate_id]=KG-0000",
                      "interview_time": "Thursday 02 October, 11:00 AM IST", "privacy_notice": settings.privacy_notice(),
                      "company": "Kargo"}
            preview = {"subject": b["subject"].format(**fields), "body": b["body"].format(**fields)}
        except (KeyError, ValueError, IndexError) as exc:
            errs = [f"can't preview: {exc}"]
    return {"errors": errs, "preview": preview}


@router.post("/templates/reset")
async def reset_template(request: Request, u=Depends(need("admin"))):
    b = await request.json()
    emails.reset_template(b["kind"], b.get("role", "*"), u["username"])
    return _ok()


@router.get("/privacy/export/{cid}")
def export(cid: str, u=Depends(need("admin"))):
    data = json.dumps(privacy.export(cid.upper()), indent=2, ensure_ascii=False, default=str)
    return Response(data, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{cid.upper()}-data.json"'})


@router.post("/privacy/erase")
async def erase(request: Request, u=Depends(need("admin"))):
    b = await request.json()
    try:
        privacy.erase(b["candidate_id"].strip().upper(), by=u["username"])
    except (ValueError, KeyError) as exc:
        _err(exc)
    return _ok()


@router.get("/backup.zip")
def backup(u=Depends(need("admin"))):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response(privacy.backup_bytes(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="kargo-backup-{stamp}.zip"'})


@router.get("/resend/status")
def resend_status(u=Depends(need("admin"))):
    from . import resend_client

    return {**resend_client.domain_status(), "from": config.from_email(), "reply_to": config.env("REPLY_TO"),
            "dry_run": config.dry_run(), "demo": config.is_demo(), "test_recipient": config.test_recipient() is not None,
            "webhook_secret": bool(config.env("RESEND_WEBHOOK_SECRET")),
            "webhook_url": f"{config.public_base_url()}/api/webhooks/resend"}


@router.post("/resend/test")
async def resend_test(request: Request, u=Depends(need("admin"))):
    """Send a real test email to the signed-in admin (or an address they type). Never a candidate."""
    b = await request.json()
    to = (b.get("to") or u.get("email") or "").strip()
    if not to or "@" not in to:
        raise HTTPException(400, "add your email address first (Settings > Team) or type one")
    try:
        pid = emails.send_test(to, u["username"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, emails._safe_error(exc))
    return _ok(id=pid, to=to)


@router.post("/digest-now")
def digest_now(u=Depends(need("admin"))):
    automation.daily_digest(datetime.now(timezone.utc), force=True)
    return _ok()


# ---------------------------------------------------------------- cron

@router.get("/cron/tick")
def cron_tick(request: Request):
    """Vercel Cron: sends due emails, reminders, digest, retention; scores a few waiting CVs."""
    secret = config.env("CRON_SECRET")
    if not secret or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {secret}"):
        raise HTTPException(401, "unauthorised")
    result = {"ok": True}
    for mode in config.available_modes():  # the demo and the real product each get their own pass
        with config.use_mode(mode):
            try:
                out = automation.tick(log=lambda *_: None, score_limit=int(os.environ.get("CRON_SCORE_LIMIT", "3")))
                result[mode] = {k: v for k, v in out.items() if not isinstance(v, (list, dict))}
            except Exception as exc:  # noqa: BLE001 - one product failing mustn't stop the other
                result[mode] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return result
