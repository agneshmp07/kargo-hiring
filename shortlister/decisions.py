"""The human layer (G2): Invite (Advance) / Pass / Hold, plus what happens after an invite:
interview stages, scorecards, second opinions and comments. Everything is logged."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from . import config, emails, store
from .pipeline import primary_role

DECISIONS = ("Advance", "Pass", "Hold")
FINAL = ("Advance", "Pass")  # these trigger an email; changeable only inside the undo window

STAGES = {
    "invited": "Invited, waiting to book",
    "scheduled": "Interview booked",
    "interviewed": "Interviewed, awaiting outcome",
    "selected": "Selected (offer handled outside this system)",
    "not_selected": "Not selected after interview",
    "withdrawn": "Withdrew",
}
OUTCOME_STAGES = ("selected", "not_selected", "withdrawn")
RECOMMENDATIONS = ("strong_yes", "yes", "no", "strong_no")


class DecisionError(RuntimeError):
    pass


# ---------------------------------------------------------------- decisions

def record(candidate_id: str, role: str, decision: str, source: str = "card", sender=None,
           by: str | None = None) -> dict:
    """Log the decision with a snapshot of what was shown, then queue the email."""
    if decision not in DECISIONS:
        raise DecisionError(f"unknown decision {decision!r}")
    with store.connect() as conn:
        cand = store.get_candidate(conn, candidate_id)
        if not cand:
            raise DecisionError(f"unknown candidate {candidate_id}")
        results = cand["results_json"]
        if role not in results:
            raise DecisionError(f"{candidate_id} was not scored for {role}")
        prev = store.latest_decision(conn, candidate_id)
        if prev and prev["decision"] in FINAL:
            raise DecisionError(f"{candidate_id} already has a final decision ({prev['decision']})")
        r = results[role]
        rationale = (cand["llm_json"] or {}).get("rationale", "")
        decision_id = conn.execute(
            "INSERT INTO decisions (ts, candidate_id, role, band, final, layer_a, layer_b, gate, floors, "
            "rationale_shown, decision, source, decided_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (store.now(), candidate_id, role, r["band"], r["final"], r["layer_a"], r["layer_b"], r["gate"],
             json.dumps(r["adjustments"]), rationale, decision, source, by),
        ).fetchone()["id"]
        if decision == "Advance":
            _set_stage(conn, candidate_id, role, "invited", by)
    store.audit("decision", decision_id=decision_id, candidate_id=candidate_id, role=role,
                band=r["band"], final=r["final"], layer_a=r["layer_a"], layer_b=r["layer_b"],
                gate=r["gate"], floors=r["floors"], rationale_shown=rationale, decision=decision,
                source=source, decided_by=by)
    email = emails.dispatch(decision_id, sender=sender) if decision in FINAL else None
    return {"decision_id": decision_id, "email": email}


def undo(decision_id: int, by: str | None = None) -> None:
    """Undo a decision while its email is still waiting in the undo window (or for a Hold)."""
    with store.connect() as conn:
        d = store.one(conn, "SELECT * FROM decisions WHERE id = ?", (decision_id,))
    if not d or d["undone_at"]:
        raise DecisionError("nothing to undo")
    ok, why = emails.cancel_for_decision(decision_id, by or "unknown")
    if not ok:
        raise DecisionError(f"too late to undo: {why}")
    with store.connect() as conn:
        conn.execute("UPDATE decisions SET undone_at = ?, undone_by = ? WHERE id = ?", (store.now(), by, decision_id))
        if d["decision"] == "Advance":
            conn.execute("DELETE FROM stages WHERE candidate_id = ?", (d["candidate_id"],))
    store.audit("decision_undone", decision_id=decision_id, candidate_id=d["candidate_id"],
                decision=d["decision"], by=by)


def undoable(conn, decision: dict) -> bool:
    if not decision or decision["undone_at"]:
        return False
    if decision["decision"] == "Hold":
        return True
    msgs = store.rows(conn, "SELECT status FROM emails WHERE decision_id = ?", (decision["id"],))
    return bool(msgs) and all(m["status"] in ("scheduled", "cancelled") for m in msgs)


def bulk_pass_candidates(role: str) -> list[str]:
    """Undecided 'Not a fit' candidates in this role group, excluding any CV in an
    unanswered spot-check or one flagged as missed."""
    with store.connect() as conn:
        protected = {r["candidate_id"] for r in conn.execute(
            "SELECT candidate_id FROM spot_checks WHERE verdict IS NULL OR verdict = 'missed'")}
        out = []
        for c in store.all_candidates(conn):
            if primary_role(c) != role or c["id"] in protected:
                continue
            if c["results_json"][role]["band"] != "Not a fit":
                continue
            prev = store.latest_decision(conn, c["id"])
            if prev is None or prev["decision"] == "Hold":
                out.append(c["id"])
    return out


def bulk_pass(role: str, sender=None, by: str | None = None) -> list[dict]:
    """The bulk "Pass all Not a fit" click."""
    return [record(cid, role, "Pass", source="bulk", sender=sender, by=by) for cid in bulk_pass_candidates(role)]


def spot_check_verdict(spot_id: int, verdict: str, by: str | None = None) -> None:
    if verdict not in ("correct", "missed"):
        raise DecisionError("verdict must be 'correct' or 'missed'")
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM spot_checks WHERE id = ?", (spot_id,)).fetchone()
        conn.execute("UPDATE spot_checks SET verdict = ?, ts = ?, by_user = ? WHERE id = ?",
                     (verdict, store.now(), by, spot_id))
    store.audit("spot_check_verdict", spot_id=spot_id, candidate_id=row["candidate_id"],
                batch_id=row["batch_id"], verdict=verdict, by=by)


def hold_reminders(now: datetime | None = None) -> list[dict]:
    """Candidates whose latest decision is Hold and is at least 7 days old."""
    now = now or datetime.now(timezone.utc)
    out = []
    with store.connect() as conn:
        for c in store.all_candidates(conn):
            prev = store.latest_decision(conn, c["id"])
            if prev and prev["decision"] == "Hold":
                held = datetime.fromisoformat(prev["ts"])
                if now - held >= timedelta(days=config.HOLD_REMINDER_DAYS):
                    out.append({"candidate_id": c["id"], "role": prev["role"], "held_since": prev["ts"],
                                "days": (now - held).days})
    return out


# ---------------------------------------------------------------- interview stages

def _set_stage(conn, cid, role, stage, by, scheduled_for=None, booking_ref=None, note=None):
    conn.execute(
        "INSERT INTO stages (candidate_id, role, stage, scheduled_for, booking_ref, outcome_note, updated_at, "
        "updated_by) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET stage = excluded.stage, "
        "scheduled_for = COALESCE(excluded.scheduled_for, stages.scheduled_for), "
        "booking_ref = COALESCE(excluded.booking_ref, stages.booking_ref), "
        "outcome_note = COALESCE(excluded.outcome_note, stages.outcome_note), "
        "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
        (cid, role, stage, scheduled_for, booking_ref, note, store.now(), by))
    store.audit("stage", _conn=conn, candidate_id=cid, stage=stage, scheduled_for=scheduled_for, by=by)


def set_stage(cid: str, stage: str, by: str | None, scheduled_for: str | None = None,
              booking_ref: str | None = None, note: str | None = None) -> None:
    """Move an invited candidate through the interview stages. 'Not selected' queues the
    post-interview email (a human outcome, so it is allowed). 'Selected' sends nothing:
    offers stay outside this system."""
    if stage not in STAGES:
        raise DecisionError(f"unknown stage {stage}")
    with store.connect() as conn:
        st = store.one(conn, "SELECT * FROM stages WHERE candidate_id = ?", (cid,))
        if not st:
            raise DecisionError(f"{cid} has not been invited")
        if st["stage"] in OUTCOME_STAGES:
            raise DecisionError(f"{cid} already has an outcome ({STAGES[st['stage']]})")
        _set_stage(conn, cid, st["role"], stage, by, scheduled_for, booking_ref, note)
        invite = store.one(conn, "SELECT id FROM decisions WHERE candidate_id = ? AND decision = 'Advance' "
                                 "AND undone_at IS NULL ORDER BY id DESC LIMIT 1", (cid,))
    if stage == "not_selected" and invite:
        from . import settings

        emails.queue_followup_message("post_interview_rejection", invite["id"],
                                      delay_minutes=int(settings.get("undo_minutes") or 0))


def stages() -> list[dict]:
    with store.connect() as conn:
        return store.rows(conn, "SELECT * FROM stages ORDER BY updated_at DESC")


def find_candidate_for_booking(candidate_id: str | None, email: str | None) -> str | None:
    """Match a booking webhook to an invited candidate by ID tag, falling back to email."""
    from . import vault

    with store.connect() as conn:
        invited = {r["candidate_id"] for r in conn.execute("SELECT candidate_id FROM stages")}
    if candidate_id and candidate_id in invited:
        return candidate_id
    if email:
        for cid in invited:
            if (vault.get(cid).get("email") or "").lower() == email.lower():
                return cid
    return None


# ---------------------------------------------------------------- scorecards

def add_scorecard(cid: str, interviewer: str, ratings: dict, recommendation: str, notes: str) -> int:
    if recommendation not in RECOMMENDATIONS:
        raise DecisionError("pick a recommendation")
    with store.connect() as conn:
        if not store.one(conn, "SELECT 1 AS x FROM stages WHERE candidate_id = ?", (cid,)):
            raise DecisionError("scorecards are for invited candidates")
        sid = conn.execute("INSERT INTO scorecards (candidate_id, interviewer, ratings, recommendation, notes, ts) "
                           "VALUES (?,?,?,?,?,?) RETURNING id",
                           (cid, interviewer, json.dumps(ratings), recommendation, notes.strip(),
                            store.now())).fetchone()["id"]
        store.audit("scorecard", _conn=conn, candidate_id=cid, interviewer=interviewer, recommendation=recommendation)
    return sid


def scorecards(cid: str | None = None) -> list[dict]:
    with store.connect() as conn:
        if cid:
            out = store.rows(conn, "SELECT * FROM scorecards WHERE candidate_id = ? ORDER BY id", (cid,))
        else:
            out = store.rows(conn, "SELECT * FROM scorecards ORDER BY id")
    for s in out:
        s["ratings"] = json.loads(s["ratings"] or "{}")
    return out


# ---------------------------------------------------------------- second opinions

def request_review(cid: str, role: str, requested_by: str, assignee: str) -> int:
    if requested_by == assignee:
        raise DecisionError("pick someone else for a second opinion")
    with store.connect() as conn:
        rid = conn.execute("INSERT INTO reviews (candidate_id, role, requested_by, assignee, status, requested_at) "
                           "VALUES (?,?,?,?, 'open', ?) RETURNING id",
                           (cid, role, requested_by, assignee, store.now())).fetchone()["id"]
        store.audit("review_requested", _conn=conn, candidate_id=cid, by=requested_by, assignee=assignee)
    return rid


def answer_review(review_id: int, by: str, opinion: str, note: str) -> None:
    if opinion not in DECISIONS:
        raise DecisionError("opinion must be Advance, Pass or Hold")
    with store.connect() as conn:
        r = store.one(conn, "SELECT * FROM reviews WHERE id = ?", (review_id,))
        if not r or r["assignee"] != by:
            raise DecisionError("this review is not assigned to you")
        conn.execute("UPDATE reviews SET status = 'done', opinion = ?, note = ?, answered_at = ? WHERE id = ?",
                     (opinion, note.strip(), store.now(), review_id))
        store.audit("review_answered", _conn=conn, candidate_id=r["candidate_id"], by=by, opinion=opinion)


def reviews(cid: str | None = None, assignee: str | None = None, open_only: bool = False) -> list[dict]:
    sql, args = "SELECT * FROM reviews WHERE 1=1", []
    if cid:
        sql, args = sql + " AND candidate_id = ?", [*args, cid]
    if assignee:
        sql, args = sql + " AND assignee = ?", [*args, assignee]
    if open_only:
        sql += " AND status = 'open'"
    with store.connect() as conn:
        return store.rows(conn, sql + " ORDER BY id DESC", args)


# ---------------------------------------------------------------- comments

MENTION_RE = re.compile(r"@([a-z0-9._-]{2,32})")


def add_comment(cid: str, author: str, body: str) -> int:
    body = body.strip()
    if not body:
        raise DecisionError("write something first")
    mentions = sorted(set(MENTION_RE.findall(body.lower())))
    with store.connect() as conn:
        c = conn.execute("INSERT INTO comments (candidate_id, author, body, mentions, ts) VALUES (?,?,?,?,?) "
                         "RETURNING id", (cid, author, body[:4000], json.dumps(mentions), store.now())).fetchone()
        store.audit("comment", _conn=conn, candidate_id=cid, author=author, mentions=mentions)
    return c["id"]


def comments(cid: str | None = None, since: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM comments WHERE 1=1", []
    if cid:
        sql, args = sql + " AND candidate_id = ?", [*args, cid]
    if since:
        sql, args = sql + " AND ts >= ?", [*args, since]
    with store.connect() as conn:
        out = store.rows(conn, sql + " ORDER BY id", args)
    for c in out:
        c["mentions"] = json.loads(c["mentions"] or "[]")
    return out
