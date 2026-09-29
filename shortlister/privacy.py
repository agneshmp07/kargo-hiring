"""Data protection (India's DPDP Act 2023): erase on request, export on request,
automatic retention clean-up, and backups."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

from . import config, cvstore, settings, store, vault

TABLES = ("candidates", "decisions", "emails", "spot_checks", "batches", "audit_log", "users", "comments",
          "reviews", "stages", "scorecards", "calibration", "settings", "params_versions", "webhook_events",
          "inbound_messages")


def erase(cid: str, by: str, reason: str = "request") -> None:
    """Delete everything that identifies the candidate. The anonymous decision record
    (ID, band, scores, decision) is kept so the audit trail stays complete."""
    with store.connect() as conn:
        c = store.one(conn, "SELECT file_name, erased_at FROM candidates WHERE id = ?", (cid,))
        if not c:
            raise ValueError(f"unknown candidate {cid}")
        if c["erased_at"]:
            return
        conn.execute("UPDATE candidates SET redacted_text = NULL, llm_json = NULL, evidence_flags = NULL, "
                     "redaction_removed = NULL, file_name = ?, erased_at = ? WHERE id = ?",
                     (f"[erased]/{cid}", store.now(), cid))
        conn.execute("UPDATE comments SET body = '[erased]' WHERE candidate_id = ?", (cid,))
        conn.execute("UPDATE scorecards SET notes = '[erased]' WHERE candidate_id = ?", (cid,))
        conn.execute("UPDATE reviews SET note = '[erased]' WHERE candidate_id = ?", (cid,))
        conn.execute("UPDATE emails SET to_addr = '[erased]', body = '[erased]' WHERE candidate_id = ?", (cid,))
        conn.execute("UPDATE decisions SET rationale_shown = '[erased]' WHERE candidate_id = ?", (cid,))
        store.audit("candidate_erased", _conn=conn, candidate_id=cid, by=by, reason=reason)
    cvstore.delete(c["file_name"])
    vault.delete(cid)
    if config.storage_mode() == "files":
        for p in config.OUTBOX_DIR.glob(f"*_{cid}_*"):
            p.unlink(missing_ok=True)


def export(cid: str) -> dict:
    """Everything held about one candidate, for an access request."""
    with store.connect() as conn:
        out = {
            "identity": vault.get(cid),
            "candidate": store.one(conn, "SELECT * FROM candidates WHERE id = ?", (cid,)),
            "decisions": store.rows(conn, "SELECT * FROM decisions WHERE candidate_id = ?", (cid,)),
            "stage": store.one(conn, "SELECT * FROM stages WHERE candidate_id = ?", (cid,)),
            "emails": store.rows(conn, "SELECT kind, channel, status, subject, body, created_at FROM emails "
                                       "WHERE candidate_id = ?", (cid,)),
            "comments": store.rows(conn, "SELECT author, body, ts FROM comments WHERE candidate_id = ?", (cid,)),
            "scorecards": store.rows(conn, "SELECT interviewer, recommendation, notes, ts FROM scorecards "
                                           "WHERE candidate_id = ?", (cid,)),
        }
    store.audit("candidate_exported", candidate_id=cid)
    return out


def purge_expired(now: datetime | None = None, by: str = "retention") -> list[str]:
    """Erase candidates whose final outcome is older than the retention period."""
    days = int(settings.get("retention_days") or 0)
    if days <= 0:
        return []
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat(timespec="seconds")
    erased = []
    with store.connect() as conn:
        finals = store.rows(conn, """
            SELECT d.candidate_id AS cid, MAX(d.ts) AS ts FROM decisions d
            WHERE d.undone_at IS NULL AND d.decision = 'Pass' GROUP BY d.candidate_id
            UNION
            SELECT candidate_id AS cid, updated_at AS ts FROM stages
            WHERE stage IN ('selected', 'not_selected', 'withdrawn')""")
    for f in finals:
        if f["ts"] and f["ts"] < cutoff:
            with store.connect() as conn:
                row = store.one(conn, "SELECT erased_at FROM candidates WHERE id = ?", (f["cid"],))
            if row and not row["erased_at"]:
                erase(f["cid"], by=by, reason=f"retention {days} days")
                erased.append(f["cid"])
    return erased


def backup_bytes() -> bytes:
    """Zip of every table (JSON), the vault as stored (encrypted if VAULT_KEY is set) and the CVs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        with store.connect() as conn:
            for t in TABLES:
                z.writestr(f"db/{t}.json", json.dumps(store.rows(conn, f"SELECT * FROM {t}"), ensure_ascii=False,
                                                      default=lambda b: "<binary>"))
        z.writestr("vault/identities.bin", vault.export_raw())
        for name in cvstore.names():
            z.writestr(f"applications/{name}", cvstore.read(name))
    store.audit("backup_created")
    return buf.getvalue()


def backup():
    """Write a backup zip to backups/ (local use). On Vercel, download backup_bytes() instead."""
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = config.BACKUP_DIR / f"kargo-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"
    path.write_bytes(backup_bytes())
    return path
