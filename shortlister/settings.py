"""Organisation settings (automation toggles, retention, templates, who may decide).

Stored in the database so every teammate sees the same values; every change is audited.
"""
from __future__ import annotations

from . import store

PRIVACY_NOTICE = """\
Kargo uses your CV only to assess your application for the role you applied for. Before any automated \
review, we remove your name, contact details, photo, date of birth, gender markers, marital status, college \
names and full address. A person at Kargo makes every decision about your application.

We keep application data for {retention_days} days after a final decision, then delete it. You can ask us \
to see or delete your data at any time by writing to {contact}. This notice follows India's Digital \
Personal Data Protection Act, 2023."""

DEFAULTS = {
    # Who may click Invite / Pass / Hold. The build prompt says Arjun decides, so only founders by default.
    "decision_roles": ["founder"],
    # Delay before a decision's email goes out, so a misclick can be undone.
    "undo_minutes": 10,
    # OFF by default: an acknowledgement reaches the candidate before Arjun's decision,
    # which the build prompt's overriding rule does not allow. Turning it on is Arjun's call.
    "ack_enabled": False,
    # One friendly reminder if an invited candidate hasn't booked after N days (0 = off).
    "followup_days": 3,
    # Reminder to the candidate this many hours before a booked interview (0 = off).
    "interview_reminder_hours": 24,
    # Also send invite / reminder messages on WhatsApp to candidates who opted in (careers form).
    "whatsapp_enabled": False,
    # Daily digest to the team (email and, if configured, Slack).
    "digest_enabled": True,
    "digest_hour": 9,
    "digest_recipients": [],
    "slack_enabled": False,
    # Remind decision-makers by email about Holds older than 7 days (in-app reminder is always on).
    "hold_reminder_email": True,
    # Data protection: delete application data this many days after a final decision (0 = never).
    "retention_days": 180,
    "privacy_contact": "privacy@yourcompany.com",
    "privacy_notice": PRIVACY_NOTICE,
    # Template overrides: {kind: {role or "*": {"subject": ..., "body": ...}}}
    "templates": {},
}


def get(key: str, conn=None):
    if conn is not None:
        return store.get_setting(conn, key, DEFAULTS.get(key))
    with store.connect() as c:
        return store.get_setting(c, key, DEFAULTS.get(key))


def all_settings() -> dict:
    with store.connect() as c:
        return {k: store.get_setting(c, k, v) for k, v in DEFAULTS.items()}


def put(key: str, value, by: str | None = None) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting {key}")
    with store.connect() as c:
        old = store.get_setting(c, key, DEFAULTS.get(key))
        store.put_setting(c, key, value, by)
        if key != "templates":
            store.audit("setting_changed", _conn=c, key=key, old=old, new=value, by=by)
        else:
            store.audit("templates_changed", _conn=c, by=by)


def privacy_notice() -> str:
    s = all_settings()
    return s["privacy_notice"].format(retention_days=s["retention_days"], contact=s["privacy_contact"])
