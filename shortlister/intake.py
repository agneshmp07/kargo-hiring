"""Getting CVs in: the upload screen, the public careers form, and a hiring inbox (IMAP).
Job boards (Naukri, LinkedIn) can forward applications to the hiring inbox."""
from __future__ import annotations

import email
import hashlib
import imaplib
import re
from email.header import decode_header
from pathlib import Path

from . import config, cvstore, store

ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt", ".md"}
MAX_BYTES = 10 * 1024 * 1024


def known_hashes() -> set[str]:
    with store.connect() as conn:
        return {r["file_hash"] for r in conn.execute("SELECT file_hash FROM candidates WHERE scored_at IS NOT NULL")}


def save_incoming(filename: str, data: bytes, role_code: str = "", source: str = "upload",
                  uploaded_by: str | None = None, consent: bool | None = None,
                  whatsapp_opt_in: bool = False) -> tuple[str | None, str]:
    """Store one CV in applications/ with its sidecar metadata. Returns (saved name or None, message)."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return None, f"{filename}: unsupported file type"
    if len(data) > MAX_BYTES:
        return None, f"{filename}: larger than 10 MB"
    if not data:
        return None, f"{filename}: empty file"
    if hashlib.sha256(data).hexdigest() in known_hashes():
        return None, f"{filename}: already received (same file)"
    safe = re.sub(r"[^\w.\- ()]+", "_", Path(filename).name).strip(" ._") or f"cv{ext}"
    name = cvstore.unique_name(f"{role_code}__{safe}" if role_code else safe)
    cvstore.put(name, data, {"source": source, "uploaded_by": uploaded_by, "consent": consent,
                             "whatsapp_opt_in": bool(whatsapp_opt_in), "received_at": store.now()})
    store.audit("cv_received", file=name, source=source, by=uploaded_by)
    return name, f"{filename}: saved"


def inbox_configured() -> bool:
    return bool(config.env("HIRING_IMAP_HOST") and config.env("HIRING_IMAP_USER")
                and config.env("HIRING_IMAP_PASSWORD"))


def _decode(s: str | None) -> str:
    if not s:
        return ""
    return "".join(p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
                   for p, enc in decode_header(s))


def _role_from_subject(subject: str) -> str:
    from . import versions

    names = versions.role_names(versions.active())
    for code, name in sorted(names.items(), key=lambda kv: -len(kv[1])):
        if re.search(re.escape(name), subject, re.I) or re.search(rf"\b{code}\b", subject):
            return code
    return ""


def poll_inbox(log=print) -> int:
    """Save CV attachments from unread emails in the hiring inbox. Returns how many were saved."""
    if not inbox_configured():
        return 0
    box = imaplib.IMAP4_SSL(config.env("HIRING_IMAP_HOST"))
    saved = 0
    try:
        box.login(config.env("HIRING_IMAP_USER"), config.env("HIRING_IMAP_PASSWORD"))
        box.select(config.env("HIRING_IMAP_FOLDER") or "INBOX")
        _, ids = box.search(None, "UNSEEN")
        for num in ids[0].split():
            _, data = box.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            mid = msg.get("Message-ID") or f"no-id-{num.decode()}"
            with store.connect() as conn:
                if conn.execute("SELECT 1 FROM inbound_messages WHERE message_id = ?", (mid,)).fetchone():
                    continue
            role = _role_from_subject(_decode(msg.get("Subject")))
            files = []
            for part in msg.walk():
                fname = _decode(part.get_filename())
                if not fname or Path(fname).suffix.lower() not in ALLOWED_EXT:
                    continue
                name, note = save_incoming(fname, part.get_payload(decode=True) or b"", role, source="inbox")
                log(note)
                if name:
                    files.append(name)
                    saved += 1
            with store.connect() as conn:
                conn.execute("INSERT OR IGNORE INTO inbound_messages (message_id, received_at, files) VALUES (?,?,?)",
                             (mid, store.now(), ",".join(files)))
            box.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
    return saved
