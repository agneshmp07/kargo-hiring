"""All outgoing messages: candidate emails, optional WhatsApp, and internal digests.

Rules enforced here:
- A candidate message exists only because a person decided something: a logged (not undone)
  Invite/Pass decision, or a logged interview outcome. Follow-ups and interview reminders hang off
  the Invite decision. The only exception is the receipt acknowledgement, which is OFF unless
  an admin switches it on (settings.ack_enabled).
- Decision emails wait `undo_minutes` before sending, so a misclick can be undone.
- DRY_RUN defaults to true (and demo mode is always dry run): messages go to outbox/.
- TEST_RECIPIENT / TEST_WHATSAPP, when set, replace every real recipient.
- API keys are read from the environment at send time and never logged.
- No offer template exists, and templates containing scores, reasons or offer language are refused.
"""
from __future__ import annotations

import json
import os
import re
import string
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from . import config, store, vault

CANDIDATE_KINDS = ("invite", "rejection", "followup", "interview_reminder", "post_interview_rejection", "ack")
INTERNAL_KINDS = ("digest", "hold_reminder")
WHATSAPP_KINDS = ("invite", "followup", "interview_reminder")
PLACEHOLDERS = {"first_name", "role_name", "scheduling_link", "interview_time", "privacy_notice", "company"}
BANNED_RE = re.compile(r"\b(score|scored|band|not a fit|borderline|layer [ab]|gate|p[1-5]|n[12]|offer letter|"
                       r"pleased to offer|job offer|offer of employment|ctc|compensation package|salary)\b", re.I)
SIGNATURE = "Kargo Hiring, on behalf of Arjun Mehta\nKargo, Mumbai\n"


class NoDecisionError(RuntimeError):
    pass


DEFAULT_TEMPLATES = {
    "invite": {"*": {
        "subject": "Interview invitation: {role_name} at Kargo",
        "body": "Hi {first_name},\n\nThank you for applying for the {role_name} role at Kargo. We enjoyed reading "
                "about your work and would like to invite you to an interview with Arjun Mehta, our founder.\n\n"
                "Please pick a time that suits you here: {scheduling_link}\n\nThe conversation will take about 45 "
                "minutes. We will talk about how you have worked with operations teams, decisions you have owned, "
                "and what you would want to build at Kargo. There's nothing to prepare beyond that.\n\n"
                "Looking forward to speaking with you.\n\n" + SIGNATURE}},
    "rejection": {
        "PM": {"subject": "Your application for Product Manager at Kargo",
               "body": "Hi {first_name},\n\nThank you for applying for the Product Manager role at Kargo and for "
                       "the time you put into your application.\n\nThis role is our first PM position on the core "
                       "operations platform that freight-forwarding teams use every day. After reviewing every "
                       "application carefully, we have decided not to take your application forward for this "
                       "role.\n\nWe know this isn't the news you were hoping for, and we're grateful you considered "
                       "Kargo. We wish you the very best in what comes next.\n\n" + SIGNATURE},
        "SPM": {"subject": "Your application for Senior Product Manager at Kargo",
                "body": "Hi {first_name},\n\nThank you for applying for the Senior Product Manager role at Kargo and "
                        "for the time you put into your application.\n\nThis role owns the integration and data "
                        "layer of our platform at an early stage in the product function's life. After reviewing "
                        "every application carefully, we have decided not to take your application forward for "
                        "this role.\n\nWe know this isn't the news you were hoping for, and we're grateful you "
                        "considered Kargo. We wish you the very best in what comes next.\n\n" + SIGNATURE},
        "*": {"subject": "Your application for {role_name} at Kargo",
              "body": "Hi {first_name},\n\nThank you for applying for the {role_name} role at Kargo and for the time "
                      "you put into your application.\n\nAfter reviewing every application carefully, we have "
                      "decided not to take your application forward for this role.\n\nWe're grateful you "
                      "considered Kargo and wish you the very best in what comes next.\n\n" + SIGNATURE}},
    "followup": {"*": {
        "subject": "A quick reminder: interview for {role_name} at Kargo",
        "body": "Hi {first_name},\n\nJust a gentle reminder that we'd love to meet you for the {role_name} role. "
                "If you're still interested, you can pick a time here: {scheduling_link}\n\nIf the timing doesn't "
                "work or your plans have changed, simply reply and let us know.\n\n" + SIGNATURE}},
    "interview_reminder": {"*": {
        "subject": "Tomorrow: your Kargo interview for {role_name}",
        "body": "Hi {first_name},\n\nA reminder that your interview for the {role_name} role is scheduled for "
                "{interview_time}. If you need to move it, use the link in your booking confirmation.\n\n"
                "See you soon.\n\n" + SIGNATURE}},
    "post_interview_rejection": {"*": {
        "subject": "Your {role_name} interview at Kargo",
        "body": "Hi {first_name},\n\nThank you for taking the time to interview for the {role_name} role. We "
                "enjoyed the conversation. After careful thought, we have decided not to move forward with your "
                "application this time.\n\nWe appreciate your interest in Kargo and wish you every success.\n\n"
                + SIGNATURE}},
    "ack": {"*": {
        "subject": "We've received your application for {role_name}",
        "body": "Hi {first_name},\n\nThank you for applying to Kargo. We've received your application for "
                "{role_name}. A person at Kargo reviews every application and we'll get back to you either "
                "way.\n\nHow we handle your data:\n{privacy_notice}\n\n" + SIGNATURE}},
}
WHATSAPP_TEXT = {
    "invite": "Hi {first_name}, this is Kargo. We'd like to invite you to interview for {role_name}. "
              "Pick a time here: {scheduling_link}",
    "followup": "Hi {first_name}, a gentle reminder from Kargo: you can book your {role_name} interview here: "
                "{scheduling_link}",
    "interview_reminder": "Hi {first_name}, a reminder from Kargo: your {role_name} interview is at {interview_time}.",
}


# ---------------------------------------------------------------- templates

def templates() -> dict:
    from . import settings

    merged = json.loads(json.dumps(DEFAULT_TEMPLATES))
    for kind, per_role in (settings.get("templates") or {}).items():
        merged.setdefault(kind, {}).update(per_role)
    return merged


def template_for(kind: str, role: str | None) -> dict:
    t = templates()[kind]
    return t.get(role or "*") or t["*"]


def validate_template(subject: str, body: str) -> list[str]:
    errs = []
    for part in (subject, body):
        try:
            names = {f for _, f, _, _ in string.Formatter().parse(part) if f}
        except ValueError as exc:
            errs.append(f"formatting problem: {exc}")
            continue
        unknown = names - PLACEHOLDERS
        if unknown:
            errs.append("unknown placeholder(s): " + ", ".join("{" + u + "}" for u in sorted(unknown)))
    m = BANNED_RE.search(subject + " " + body)
    if m:
        errs.append(f"candidate emails must not mention scores, reasons or offers (found '{m.group()}')")
    return errs


def save_template(kind: str, role: str, subject: str, body: str, by: str) -> None:
    from . import settings

    if kind not in DEFAULT_TEMPLATES:
        raise ValueError(f"unknown template {kind}")
    errs = validate_template(subject, body)
    if errs:
        raise ValueError("; ".join(errs))
    t = settings.get("templates") or {}
    t.setdefault(kind, {})[role] = {"subject": subject, "body": body}
    settings.put("templates", t, by)


def reset_template(kind: str, role: str, by: str) -> None:
    from . import settings

    t = settings.get("templates") or {}
    t.get(kind, {}).pop(role, None)
    settings.put("templates", t, by)


def _first_name(name: str | None) -> str:
    if not name:
        return "there"
    first = name.split()[0]
    return first.capitalize() if first.isupper() else first


def personalized_link(role: str, candidate_id: str) -> str | None:
    """Scheduling link tagged with the pseudonymous candidate ID so bookings can be matched
    (Cal.com metadata / Calendly utm_content). Never puts name or email in the URL."""
    base = config.scheduling_link(role)
    if not base:
        return None
    host = urlparse(base).netloc.lower()
    q = ({"metadata[candidate_id]": candidate_id} if "cal.com" in host else
         {"utm_content": candidate_id} if "calendly.com" in host else {"ref": candidate_id})
    return base + ("&" if "?" in base else "?") + urlencode(q)


def render(kind: str, role: str | None, identity: dict, candidate_id: str | None, extra: dict | None = None,
           whatsapp: bool = False) -> tuple[str, str]:
    from . import settings, versions

    names = versions.role_names(versions.active())
    fields = {
        "first_name": _first_name(identity.get("name")),
        "role_name": names.get(role, config.ROLE_NAMES.get(role, role or "the role")),
        "scheduling_link": (personalized_link(role, candidate_id) if candidate_id else None) or "{{SCHEDULING_LINK}}",
        "interview_time": "your booked time",
        "privacy_notice": settings.privacy_notice(),
        "company": "Kargo",
        **(extra or {}),
    }
    if whatsapp:
        return "", WHATSAPP_TEXT[kind].format(**fields)
    t = template_for(kind, role)
    return t["subject"].format(**fields), t["body"].format(**fields)


# ---------------------------------------------------------------- queueing

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _insert(conn, *, decision_id, candidate_id, kind, channel, to_addr, subject, body, purpose, send_after):
    if BANNED_RE.search(subject + " " + body) and kind in CANDIDATE_KINDS:
        raise RuntimeError("refusing to send a candidate message that mentions scores, reasons or offers")
    row = conn.execute(
        "INSERT OR IGNORE INTO emails (decision_id, candidate_id, kind, channel, purpose, to_addr, subject, body, "
        "status, attempts, send_after, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
        (decision_id, candidate_id, kind, channel, purpose, to_addr, subject, body, "scheduled", 0,
         send_after.isoformat(timespec="seconds"), store.now(), store.now()),
    ).fetchone()
    return row["id"] if row else None


def _undo_minutes() -> int:
    from . import settings

    return int(settings.get("undo_minutes") or 0)


def _whatsapp_ok(conn, candidate_id: str) -> bool:
    from . import settings

    if not settings.get("whatsapp_enabled", conn):
        return False
    r = conn.execute("SELECT whatsapp_opt_in FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    return bool(r and r["whatsapp_opt_in"])


def dispatch(decision_id: int, sender=None) -> dict | None:
    """Create the one email for a logged Invite/Pass decision (plus WhatsApp for invites when the
    candidate opted in). Waits `undo_minutes` before sending; 0 sends at once. Returns the email row."""
    delay = _undo_minutes()
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        if row is None:
            raise NoDecisionError(f"no logged decision with id {decision_id}; refusing to create an email")
        decision = dict(row)
        if decision["undone_at"]:
            raise NoDecisionError(f"decision {decision_id} was undone; refusing to create an email")
        if decision["decision"] == "Hold":
            return None
        kind = "invite" if decision["decision"] == "Advance" else "rejection"
        existing = store.email_for_decision(conn, decision_id, kind)
        if existing:
            return dict(existing)
        identity = vault.get(decision["candidate_id"])
        subject, body = render(kind, decision["role"], identity, decision["candidate_id"])
        when = _now() + timedelta(minutes=delay)
        email_id = _insert(conn, decision_id=decision_id, candidate_id=decision["candidate_id"], kind=kind,
                           channel="email", to_addr=identity.get("email"), subject=subject, body=body,
                           purpose="decision", send_after=when)
        if kind in WHATSAPP_KINDS and _whatsapp_ok(conn, decision["candidate_id"]):
            _, text = render(kind, decision["role"], identity, decision["candidate_id"], whatsapp=True)
            _insert(conn, decision_id=decision_id, candidate_id=decision["candidate_id"], kind=kind,
                    channel="whatsapp", to_addr=identity.get("phone"), subject="", body=text,
                    purpose="decision", send_after=when)
    if delay <= 0:
        send_due(sender=sender)
    with store.connect() as conn:
        return store.one(conn, "SELECT * FROM emails WHERE id = ?", (email_id,))


def queue_followup_message(kind: str, decision_id: int, extra: dict | None = None, delay_minutes: int = 0) -> int | None:
    """Automated messages that follow an Invite decision: follow-up nudge, interview reminder,
    and the post-interview rejection (which also needs a logged interview outcome)."""
    if kind not in ("followup", "interview_reminder", "post_interview_rejection"):
        raise ValueError(kind)
    with store.connect() as conn:
        d = store.one(conn, "SELECT * FROM decisions WHERE id = ? AND undone_at IS NULL", (decision_id,))
        if not d or d["decision"] != "Advance":
            raise NoDecisionError("follow-up messages need a logged Invite decision")
        if kind == "post_interview_rejection":
            st = store.one(conn, "SELECT * FROM stages WHERE candidate_id = ?", (d["candidate_id"],))
            if not st or st["stage"] != "not_selected":
                raise NoDecisionError("a post-interview message needs a logged interview outcome")
        identity = vault.get(d["candidate_id"])
        subject, body = render(kind, d["role"], identity, d["candidate_id"], extra)
        when = _now() + timedelta(minutes=delay_minutes)
        eid = _insert(conn, decision_id=decision_id, candidate_id=d["candidate_id"], kind=kind, channel="email",
                      to_addr=identity.get("email"), subject=subject, body=body, purpose="automation", send_after=when)
        if kind in WHATSAPP_KINDS and _whatsapp_ok(conn, d["candidate_id"]):
            _, text = render(kind, d["role"], identity, d["candidate_id"], extra, whatsapp=True)
            _insert(conn, decision_id=decision_id, candidate_id=d["candidate_id"], kind=kind, channel="whatsapp",
                    to_addr=identity.get("phone"), subject="", body=text, purpose="automation", send_after=when)
    if delay_minutes <= 0:
        send_due()
    return eid


def queue_ack(candidate_id: str) -> int | None:
    """Receipt acknowledgement. OFF by default (settings.ack_enabled): it reaches the candidate
    before any human decision, which the build prompt's overriding rule does not allow."""
    from . import settings

    if not settings.get("ack_enabled"):
        raise NoDecisionError("acknowledgement emails are switched off (Settings > Email & automation)")
    with store.connect() as conn:
        if conn.execute("SELECT 1 FROM emails WHERE candidate_id = ? AND kind = 'ack'", (candidate_id,)).fetchone():
            return None
        cand = store.one(conn, "SELECT applied_role FROM candidates WHERE id = ?", (candidate_id,))
        identity = vault.get(candidate_id)
        if not identity.get("email"):
            return None
        subject, body = render("ack", cand["applied_role"] if cand else None, identity, candidate_id)
        eid = _insert(conn, decision_id=None, candidate_id=candidate_id, kind="ack", channel="email",
                      to_addr=identity["email"], subject=subject, body=body, purpose="ack", send_after=_now())
    send_due()
    return eid


def send_internal(kind: str, recipients: list[str], subject: str, body: str) -> list[int]:
    """Digest / reminders to the team (never to candidates)."""
    ids = []
    with store.connect() as conn:
        for to in recipients:
            r = conn.execute(
                "INSERT INTO emails (candidate_id, kind, channel, purpose, to_addr, subject, body, status, attempts, "
                "send_after, created_at, updated_at) VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (kind, "email", "internal", to, subject, body, "scheduled", 0, store.now(), store.now(), store.now()),
            ).fetchone()
            ids.append(r["id"])
    send_due()
    return ids


def cancel_for_decision(decision_id: int, by: str) -> tuple[bool, str]:
    """Undo support: cancel every not-yet-sent message of a decision. Fails if one already went out."""
    with store.connect() as conn:
        msgs = store.rows(conn, "SELECT id, status FROM emails WHERE decision_id = ?", (decision_id,))
        gone = [m for m in msgs if m["status"] in ("sent", "dry_run", "bounced", "delivered")]
        if gone:
            return False, "the email has already gone out"
        for m in msgs:
            conn.execute("UPDATE emails SET status = 'cancelled', updated_at = ? WHERE id = ?", (store.now(), m["id"]))
        store.audit("messages_cancelled", _conn=conn, decision_id=decision_id, count=len(msgs), by=by)
    return True, "cancelled"


def send_due(now: datetime | None = None, sender=None, wa_sender=None) -> int:
    """Deliver every scheduled message whose undo window has passed."""
    now = (now or _now()).isoformat(timespec="seconds")
    with store.connect() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM emails WHERE status = 'scheduled' AND send_after <= ? ORDER BY id", (now,))]
    live = not config.dry_run()
    for n, i in enumerate(ids):
        if live and n:
            time.sleep(0.15)  # stay well under Resend's 10 requests/second
        deliver(i, sender=sender, wa_sender=wa_sender)
    return len(ids)


# ---------------------------------------------------------------- delivery

def deliver(email_id: int, sender=None, wa_sender=None) -> dict:
    """Send (or write to outbox in dry run). One retry on failure, then 'failed'."""
    with store.connect() as conn:
        email = store.one(conn, "SELECT * FROM emails WHERE id = ?", (email_id,))
    if email["status"] in ("cancelled", "sent", "delivered", "dry_run", "sending"):
        return email
    # Claim it: if the cron job and a page load reach the same email at once, only one sends.
    with store.connect() as conn:
        claimed = conn.execute("UPDATE emails SET status = 'sending', updated_at = ? WHERE id = ? AND status = ?",
                               (store.now(), email_id, email["status"])).rowcount
    if claimed != 1:
        with store.connect() as conn:
            return store.one(conn, "SELECT * FROM emails WHERE id = ?", (email_id,))
    whatsapp = email["channel"] == "whatsapp"

    if config.dry_run():
        path = _write_outbox(email) if config.storage_mode() == "files" else None
        _update(email_id, status="dry_run", outbox_path=str(path) if path else None, attempts=email["attempts"])
    else:
        override = config.env("TEST_WHATSAPP") if whatsapp else config.test_recipient()
        to = override or email["to_addr"]
        problem = None
        if not to:
            problem = "no phone number on the CV" if whatsapp else "no recipient email address found"
        elif "{{SCHEDULING_LINK}}" in email["body"]:
            problem = "SCHEDULING_LINK is not set; refusing to send an invite with a placeholder"
        if problem:
            _update(email_id, status="failed", error=problem, attempts=email["attempts"])
        else:
            if whatsapp:
                send = wa_sender or _twilio_whatsapp
            elif sender:
                send = sender
            else:
                def send(to, subject, body, _e=email):
                    return _resend_send(to=to, subject=subject, body=body, email=_e)
            attempts, error, provider_id = email["attempts"], None, None
            for _ in range(2):  # first try + one retry (the idempotency key makes a retry safe)
                attempts += 1
                try:
                    provider_id = send(to=to, subject=email["subject"], body=email["body"])
                    error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    error = _safe_error(exc)
            _update(email_id, status="sent" if error is None else "failed", error=error,
                    provider_id=provider_id, attempts=attempts,
                    to_addr=email["to_addr"] if not override else f"{email['to_addr']} (test: {to})")

    with store.connect() as conn:
        final = store.one(conn, "SELECT * FROM emails WHERE id = ?", (email_id,))
    store.audit("email_status", email_id=email_id, decision_id=final["decision_id"],
                candidate_id=final["candidate_id"], kind=final["kind"], channel=final["channel"],
                status=final["status"], attempts=final["attempts"], error=final["error"])
    return final


def apply_provider_event(provider_id: str, event: str, detail: str | None = None) -> bool:
    """Resend webhook events (email.delivered / bounced / complained / failed / suppressed ...).
    A later, milder event never overwrites a worse one (e.g. delivered after bounced)."""
    from .resend_client import new_status

    with store.connect() as conn:
        row = store.one(conn, "SELECT id, status FROM emails WHERE provider_id = ?", (provider_id,))
        if not row:
            return False
        status = new_status(row["status"], event)
        conn.execute("UPDATE emails SET provider_event = ?, status = ?, error = COALESCE(?, error), updated_at = ? "
                     "WHERE id = ?", (event, status, detail, store.now(), row["id"]))
        store.audit("email_provider_event", _conn=conn, email_id=row["id"], provider_event=event, status=status)
    return True


def _update(email_id: int, **fields) -> None:
    fields["updated_at"] = store.now()
    with store.connect() as conn:
        conn.execute(f"UPDATE emails SET {', '.join(f'{k}=?' for k in fields)} WHERE id = ?",
                     [*fields.values(), email_id])


def _write_outbox(email: dict):
    config.OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    who = email["candidate_id"] or "team"
    path = config.OUTBOX_DIR / f"{email['id']:04d}_{who}_{email['kind']}_{email['channel']}.json"
    path.write_text(json.dumps({
        "channel": email["channel"], "to": email["to_addr"], "from": config.from_email(),
        "subject": email["subject"], "body": email["body"], "decision_id": email["decision_id"], "dry_run": True,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _resend_send(*, to: str, subject: str, body: str, email: dict | None = None) -> str:
    """Send through Resend with an idempotency key tied to this email row."""
    from . import resend_client

    tags = {"app": "kargo"}
    key = None
    if email:
        key = f"kargo-email-{email['id']}"
        tags.update(kind=email["kind"], candidate=email["candidate_id"] or "team")
    return resend_client.send(to=to, subject=subject, text=body, idempotency_key=key, tags=tags)


def send_test(to: str, by: str) -> str:
    """A test email from Settings, to the signed-in admin (never to a candidate)."""
    from . import resend_client

    if config.is_demo():
        raise RuntimeError("the demo never sends email")
    body = ("This is a test from Kargo hiring. If you can read this, Resend is set up correctly.\n\n"
            f"Sent by {by} at {store.now()} UTC.\n\n" + SIGNATURE)
    pid = resend_client.send(to=to, subject="Kargo hiring: test email", text=body,
                             idempotency_key=f"kargo-test-{by}-{store.now()}", tags={"app": "kargo", "kind": "test"})
    store.audit("test_email_sent", to=to, by=by, provider_id=pid)
    return pid


def _twilio_whatsapp(*, to: str, subject: str, body: str) -> str:
    """WhatsApp via Twilio. Business-initiated messages outside a 24h window need an approved
    template on your WhatsApp sender; the sandbox works for testing."""
    import requests

    sid, token, sender = (config.env("TWILIO_ACCOUNT_SID"), config.env("TWILIO_AUTH_TOKEN"),
                          config.env("TWILIO_WHATSAPP_FROM"))
    if not (sid and token and sender):
        raise RuntimeError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM not set")
    digits = re.sub(r"[^\d+]", "", to)
    if not digits.startswith("+"):
        digits = "+91" + digits[-10:]
    resp = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", auth=(sid, token),
                         data={"From": f"whatsapp:{sender}", "To": f"whatsapp:{digits}", "Body": body}, timeout=20)
    if resp.status_code >= 300:
        raise RuntimeError(f"Twilio HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("sid", "")


def post_slack(text: str) -> str:
    """Digest to Slack via an incoming webhook (dry run writes to outbox)."""
    url = config.env("SLACK_WEBHOOK_URL")
    if config.dry_run() or not url:
        if config.storage_mode() == "files":
            config.OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
            p = config.OUTBOX_DIR / f"slack_{_now().strftime('%Y%m%d-%H%M%S')}.txt"
            p.write_text(text, encoding="utf-8")
        else:
            store.audit("slack_dry_run", text=text[:2000])
        return "dry_run" if url or config.dry_run() else "no webhook configured"
    import requests

    r = requests.post(url, json={"text": text}, timeout=15)
    return "sent" if r.status_code < 300 else f"failed: HTTP {r.status_code}"


def _safe_error(exc: Exception) -> str:
    """Error text for the log, with anything key-shaped scrubbed."""
    msg = f"{type(exc).__name__}: {exc}"
    for var in ("RESEND_API_KEY", "TWILIO_AUTH_TOKEN"):
        key = os.environ.get(var)
        if key:
            msg = msg.replace(key, "[REDACTED]")
    return re.sub(r"re_[A-Za-z0-9_]{8,}", "[REDACTED]", msg)[:300]
