"""The background worker: everything that should happen without anyone clicking.

    python -m shortlister worker        (runs until stopped; one tick a minute)

Each tick: send emails whose undo window has passed, score new CVs, pull CVs from the
hiring inbox, send follow-ups and interview reminders to invited candidates, remind
decision-makers about old Holds, send the daily digest, and run retention clean-up.
The UI also runs the cheap parts (sending due emails) whenever it refreshes.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from . import auth, config, decisions, emails, settings, store


def _state(key, default=None):
    with store.connect() as conn:
        return store.get_setting(conn, f"_state.{key}", default)


def _set_state(key, value):
    with store.connect() as conn:
        store.put_setting(conn, f"_state.{key}", value, "worker")


def _team_emails(perm: str | None = None) -> list[str]:
    configured = settings.get("digest_recipients") or []
    if configured and perm is None:
        return configured
    out = []
    for u in auth.users(active_only=True):
        if u["email"] and (perm is None and u["role"] in ("founder", "hiring_manager") or perm and auth.can(u, perm)):
            out.append(u["email"])
    return out


def followups(now: datetime) -> int:
    days = int(settings.get("followup_days") or 0)
    if days <= 0:
        return 0
    n = 0
    with store.connect() as conn:
        rows = store.rows(conn, """
            SELECT d.id AS decision_id, d.ts FROM stages s JOIN decisions d
              ON d.candidate_id = s.candidate_id AND d.decision = 'Advance' AND d.undone_at IS NULL
            WHERE s.stage = 'invited'""")
        sent = {r["decision_id"] for r in conn.execute("SELECT decision_id FROM emails WHERE kind = 'followup'")}
    for r in rows:
        if r["decision_id"] not in sent and datetime.fromisoformat(r["ts"]) <= now - timedelta(days=days):
            emails.queue_followup_message("followup", r["decision_id"])
            n += 1
    return n


def interview_reminders(now: datetime) -> int:
    hours = int(settings.get("interview_reminder_hours") or 0)
    if hours <= 0:
        return 0
    n = 0
    with store.connect() as conn:
        rows = store.rows(conn, """
            SELECT s.scheduled_for, d.id AS decision_id FROM stages s JOIN decisions d
              ON d.candidate_id = s.candidate_id AND d.decision = 'Advance' AND d.undone_at IS NULL
            WHERE s.stage = 'scheduled' AND s.scheduled_for IS NOT NULL""")
        sent = {r["decision_id"] for r in conn.execute("SELECT decision_id FROM emails WHERE kind = 'interview_reminder'")}
    for r in rows:
        when = datetime.fromisoformat(r["scheduled_for"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if r["decision_id"] not in sent and now < when <= now + timedelta(hours=hours):
            ist = when.astimezone(timezone(timedelta(hours=5, minutes=30)))
            emails.queue_followup_message("interview_reminder", r["decision_id"],
                                          {"interview_time": ist.strftime("%A %d %B, %I:%M %p IST")})
            n += 1
    return n


def compose_digest(since: str | None) -> tuple[str, str]:
    from .pipeline import primary_role

    with store.connect() as conn:
        cands = store.all_candidates(conn)
        latest = {c["id"]: store.latest_decision(conn, c["id"]) for c in cands}
        stages = store.rows(conn, "SELECT * FROM stages")
        spots = conn.execute("SELECT COUNT(*) AS n FROM spot_checks WHERE verdict IS NULL").fetchone()["n"]
        failed = conn.execute("SELECT COUNT(*) AS n FROM emails WHERE status IN ('failed','bounced')").fetchone()["n"]
        reviews = store.rows(conn, "SELECT assignee, COUNT(*) AS n FROM reviews WHERE status = 'open' GROUP BY assignee")
    new = [c for c in cands if since is None or (c["scored_at"] or "") >= since]
    waiting = [c for c in cands if not latest[c["id"]] or latest[c["id"]]["decision"] == "Hold"]
    band = lambda c: c["results_json"][primary_role(c)]["band"]  # noqa: E731
    holds = decisions.hold_reminders()
    now = datetime.now(timezone.utc)
    soon = [s for s in stages if s["stage"] == "scheduled" and s["scheduled_for"]
            and now <= datetime.fromisoformat(s["scheduled_for"].replace("Z", "+00:00")).astimezone(timezone.utc)
            <= now + timedelta(hours=48)]
    mentions = decisions.comments(since=since) if since else []
    lines = [
        f"New CVs scored: {len(new)} (Strong {sum(band(c) == 'Strong' for c in new)}, "
        f"Borderline {sum(band(c) == 'Borderline' for c in new)}, Not a fit {sum(band(c) == 'Not a fit' for c in new)})",
        f"Waiting for a decision: {len(waiting)}",
        f"Random checks open: {spots}",
    ]
    if holds:
        lines.append(f"On hold 7+ days: {', '.join(h['candidate_id'] for h in holds)}")
    if soon:
        lines.append(f"Interviews in the next 48 hours: {', '.join(s['candidate_id'] for s in soon)}")
    for r in reviews:
        lines.append(f"Second opinions waiting for {r['assignee']}: {r['n']}")
    ment = [m for m in mentions if m["mentions"]]
    if ment:
        lines.append("Mentions: " + "; ".join(f"@{', @'.join(m['mentions'])} on {m['candidate_id']}" for m in ment))
    if failed:
        lines.append(f"Emails that failed or bounced: {failed} (see History)")
    subject = f"Kargo hiring digest: {len(new)} new, {len(waiting)} waiting"
    return subject, "Good morning,\n\n" + "\n".join(f"- {l}" for l in lines) + "\n\nOpen the shortlist to review.\n"


def daily_digest(now: datetime, force: bool = False) -> bool:
    if not settings.get("digest_enabled") and not force:
        return False
    today = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
    ist_hour = now.astimezone(timezone(timedelta(hours=5, minutes=30))).hour
    if not force and (_state("last_digest") == today or ist_hour < int(settings.get("digest_hour") or 9)):
        return False
    subject, body = compose_digest(_state("last_digest_ts"))
    recipients = _team_emails()
    if recipients:
        emails.send_internal("digest", recipients, subject, body)
    if settings.get("slack_enabled"):
        emails.post_slack(f"*{subject}*\n{body}")
    _set_state("last_digest", today)
    _set_state("last_digest_ts", now.isoformat(timespec="seconds"))
    store.audit("digest_sent", recipients=len(recipients))
    return True


def hold_reminder_email(now: datetime) -> bool:
    if not settings.get("hold_reminder_email"):
        return False
    today = now.date().isoformat()
    holds = decisions.hold_reminders(now)
    if not holds or _state("last_hold_reminder") == today:
        return False
    body = ("These candidates have been on hold for 7 days or more:\n\n"
            + "\n".join(f"- {h['candidate_id']} ({h['role']}), {h['days']} days" for h in holds)
            + "\n\nOpen the shortlist to decide.\n")
    to = _team_emails("decide")
    if to:
        emails.send_internal("hold_reminder", to, f"{len(holds)} candidate(s) on hold for 7+ days", body)
    _set_state("last_hold_reminder", today)
    return True


def retention(now: datetime) -> list[str]:
    from . import privacy

    today = now.date().isoformat()
    if _state("last_purge") == today:
        return []
    erased = privacy.purge_expired(now)
    _set_state("last_purge", today)
    return erased


def tick(now: datetime | None = None, log=print, score_new: bool = True, score_limit: int | None = None) -> dict:
    """One automation pass. `score_limit` caps CVs scored per pass (Vercel Cron requests are short)."""
    now = now or datetime.now(timezone.utc)
    out = {"sent": emails.send_due(now)}
    from . import intake, pipeline

    if intake.inbox_configured():
        try:
            out["inbox"] = intake.poll_inbox(log)
        except Exception as exc:  # noqa: BLE001
            log(f"inbox check failed: {exc}")
    if score_new and pipeline.pending_files():
        if config.api_ready():
            out["scored"] = pipeline.run_batch(log=log, limit=score_limit)["new"]
        elif config.is_demo():
            from .demo import keyword_classifier

            out["scored"] = pipeline.run_batch(classifier=keyword_classifier, log=log, limit=score_limit)["new"]
    out["followups"] = followups(now)
    out["reminders"] = interview_reminders(now)
    out["hold_reminder"] = hold_reminder_email(now)
    out["digest"] = daily_digest(now)
    out["erased"] = retention(now)
    out["sent"] += emails.send_due(now)
    return out


def run_forever(interval: float = 60.0, log=print) -> None:
    log(f"Kargo worker running (every {interval:.0f}s). DRY_RUN={config.dry_run()}. Ctrl+C to stop.")
    while True:
        try:
            r = tick(log=log)
            busy = {k: v for k, v in r.items() if v}
            if busy:
                log(f"{datetime.now().strftime('%H:%M:%S')} {busy}")
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the worker alive
            log(f"worker error: {type(exc).__name__}: {exc}")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            break
