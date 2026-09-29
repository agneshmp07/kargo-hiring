"""Candidate ID -> identity mapping (G4.3).

Kept apart from the scores:
- files mode: vault/identities.json on local disk
- db mode (Vercel): its own database (VAULT_DATABASE_URL, e.g. a second Neon database), falling back
  to a separate table; always encrypted on Vercel (VAULT_KEY)

Only ingest (which writes it), emails, the post-Invite name reveal, duplicate detection, privacy
requests and fairness reporting read it. llm.py and scoring.py never import this module;
tests/test_redaction.py enforces that.
"""
from __future__ import annotations

import json
import os
import re
import threading

from . import config

_LOCK = threading.Lock()
VAULT_FILE = config.VAULT_DIR / "identities.json"


def _db() -> bool:
    return config.storage_mode() == "db"


def _fernet():
    key = os.environ.get("VAULT_KEY", "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode())


def new_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def _require_key_on_vercel():
    if config.on_vercel() and not config.is_demo() and _fernet() is None:
        raise RuntimeError("VAULT_KEY must be set on Vercel so names and emails are stored encrypted")


def _enc(obj: dict) -> str:
    raw = json.dumps(obj, ensure_ascii=False)
    f = _fernet()
    return f.encrypt(raw.encode()).decode() if f else raw


def _dec(text: str) -> dict:
    if text.startswith("gAAAA"):
        f = _fernet()
        if f is None:
            raise RuntimeError("the identity vault is encrypted; set VAULT_KEY to read it")
        text = f.decrypt(text.encode()).decode()
    return json.loads(text)


# ---------------------------------------------------------------- files mode

def _load_file() -> dict:
    if not VAULT_FILE.exists():
        return {}
    raw = VAULT_FILE.read_bytes()
    if raw[:5] == b"gAAAA":
        f = _fernet()
        if f is None:
            raise RuntimeError("the identity vault is encrypted; set VAULT_KEY to read it")
        raw = f.decrypt(raw)
    return json.loads(raw.decode("utf-8"))


def _save_file(data: dict) -> None:
    config.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    f = _fernet()
    tmp = VAULT_FILE.with_suffix(".tmp")
    tmp.write_bytes(f.encrypt(raw) if f else raw)
    tmp.replace(VAULT_FILE)


# ---------------------------------------------------------------- public API

def put(candidate_id: str, *, name, email, phone, city, file_name) -> None:
    ident = {"name": name, "email": email, "phone": phone, "city": city, "file_name": file_name}
    if _db():
        _require_key_on_vercel()
        from .store import connect_vault

        with connect_vault() as c:
            c.execute("INSERT INTO vault_identities (candidate_id, data) VALUES (?, ?) "
                      "ON CONFLICT(candidate_id) DO UPDATE SET data = excluded.data", (candidate_id, _enc(ident)))
        return
    with _LOCK:
        data = _load_file()
        data[candidate_id] = ident
        _save_file(data)


def all_identities() -> dict:
    if _db():
        from .store import connect_vault

        with connect_vault() as c:
            rows = c.execute("SELECT candidate_id, data FROM vault_identities").fetchall()
        out = {}
        for r in rows:
            try:
                out[r["candidate_id"]] = _dec(r["data"])
            except Exception:  # noqa: BLE001 - wrong/missing key: treat as unreadable
                pass
        return out
    return _load_file()


def get(candidate_id: str) -> dict:
    try:
        if _db():
            from .store import connect_vault

            with connect_vault() as c:
                r = c.execute("SELECT data FROM vault_identities WHERE candidate_id = ?", (candidate_id,)).fetchone()
            return _dec(r["data"]) if r else {}
        return _load_file().get(candidate_id, {})
    except RuntimeError:
        return {}
    except Exception:  # noqa: BLE001 - e.g. InvalidToken with the wrong key
        return {}


def delete(candidate_id: str) -> bool:
    if _db():
        from .store import connect_vault

        with connect_vault() as c:
            existed = bool(c.execute("SELECT 1 FROM vault_identities WHERE candidate_id = ?",
                                     (candidate_id,)).fetchone())
            c.execute("DELETE FROM vault_identities WHERE candidate_id = ?", (candidate_id,))
        return existed
    with _LOCK:
        data = _load_file()
        existed = data.pop(candidate_id, None) is not None
        _save_file(data)
    return existed


def is_encrypted() -> bool:
    if _db():
        from .store import connect_vault

        with connect_vault() as c:
            r = c.execute("SELECT data FROM vault_identities LIMIT 1").fetchone()
        return bool(r and r["data"].startswith("gAAAA")) or (r is None and _fernet() is not None)
    return VAULT_FILE.exists() and VAULT_FILE.read_bytes()[:5] == b"gAAAA"


def encrypt_existing() -> None:
    """Re-save every identity encrypted with the current VAULT_KEY."""
    if _fernet() is None:
        raise RuntimeError("set VAULT_KEY first")
    if _db():
        for cid, ident in all_identities().items():
            put(cid, **ident)
        return
    with _LOCK:
        _save_file(_load_file())


def export_raw() -> bytes:
    """The vault exactly as stored (encrypted if a key is set), for backups."""
    if _db():
        from .store import connect_vault

        with connect_vault() as c:
            rows = [dict(r) for r in c.execute("SELECT candidate_id, data FROM vault_identities")]
        return json.dumps(rows).encode()
    return VAULT_FILE.read_bytes() if VAULT_FILE.exists() else b""


def _norm_phone(p: str | None) -> str | None:
    digits = re.sub(r"\D", "", p or "")
    return digits[-10:] if len(digits) >= 10 else None


def find_duplicates(candidate_id: str, email: str | None, phone: str | None) -> list[str]:
    """Other candidate IDs with the same email or phone number (the same person applying again)."""
    e = (email or "").strip().lower() or None
    ph = _norm_phone(phone)
    if not e and not ph:
        return []
    out = []
    for cid, ident in all_identities().items():
        if cid == candidate_id:
            continue
        if (e and (ident.get("email") or "").strip().lower() == e) or (ph and _norm_phone(ident.get("phone")) == ph):
            out.append(cid)
    return sorted(out)
