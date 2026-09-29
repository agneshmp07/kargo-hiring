"""Where CV files and their sidecar details (source, consent, opt-ins) live.

files mode: applications/ on disk plus applications/.meta/*.json (laptop, Streamlit, tests)
db mode:    the cv_files table (Vercel, whose disk is temporary)
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config, store


def _db() -> bool:
    return config.storage_mode() == "db"


def _meta_path(name: str) -> Path:
    return config.META_DIR / (name.replace("/", "__").replace("\\", "__") + ".json")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def names() -> list[str]:
    """Every stored CV, except hidden, lock and system files."""
    if _db():
        with store.connect() as c:
            return [r["file_name"] for r in c.execute("SELECT file_name FROM cv_files ORDER BY file_name")]
    folder = config.APPLICATIONS_DIR
    if not folder.exists():
        return []
    out = []
    for p in folder.rglob("*"):
        rel = p.relative_to(folder)
        if not p.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        if p.name.startswith("~$") or p.name.lower() in ("desktop.ini", "thumbs.db"):
            continue
        out.append(str(rel).replace("\\", "/"))
    return sorted(out)


def exists(name: str) -> bool:
    if _db():
        with store.connect() as c:
            return bool(c.execute("SELECT 1 FROM cv_files WHERE file_name = ?", (name,)).fetchone())
    return (config.APPLICATIONS_DIR / name).exists()


def unique_name(name: str) -> str:
    if not exists(name):
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while exists(f"{stem} ({n}){suffix}"):
        n += 1
    return f"{stem} ({n}){suffix}"


def put(name: str, data: bytes, meta: dict | None = None) -> str:
    meta = {"received_at": store.now(), **(meta or {})}
    if _db():
        with store.connect() as c:
            c.execute("INSERT INTO cv_files (file_name, data, file_hash, meta, received_at) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(file_name) DO UPDATE SET data = excluded.data, file_hash = excluded.file_hash, "
                      "meta = excluded.meta", (name, data, sha(data), json.dumps(meta), meta["received_at"]))
        return name
    config.APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    (config.APPLICATIONS_DIR / name).write_bytes(data)
    update_meta(name, **meta)
    return name


def read(name: str) -> bytes:
    if _db():
        with store.connect() as c:
            row = c.execute("SELECT data FROM cv_files WHERE file_name = ?", (name,)).fetchone()
        return bytes(row["data"]) if row else b""
    return (config.APPLICATIONS_DIR / name).read_bytes()


def file_hash(name: str) -> str:
    if _db():
        with store.connect() as c:
            row = c.execute("SELECT file_hash FROM cv_files WHERE file_name = ?", (name,)).fetchone()
        return row["file_hash"] if row else ""
    return sha(read(name))


def hashes() -> dict[str, str]:
    """name -> hash for every stored CV (one query in db mode)."""
    if _db():
        with store.connect() as c:
            return {r["file_name"]: r["file_hash"] for r in c.execute("SELECT file_name, file_hash FROM cv_files")}
    return {n: file_hash(n) for n in names()}


def meta(name: str) -> dict:
    if _db():
        with store.connect() as c:
            row = c.execute("SELECT meta FROM cv_files WHERE file_name = ?", (name,)).fetchone()
        return json.loads(row["meta"]) if row and row["meta"] else {}
    p = _meta_path(name)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def update_meta(name: str, **fields) -> None:
    merged = {**meta(name), **fields}
    if _db():
        with store.connect() as c:
            c.execute("UPDATE cv_files SET meta = ? WHERE file_name = ?", (json.dumps(merged), name))
        return
    config.META_DIR.mkdir(parents=True, exist_ok=True)
    _meta_path(name).write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")


def received_at(name: str) -> str:
    m = meta(name)
    if m.get("received_at"):
        return m["received_at"]
    if not _db() and (config.APPLICATIONS_DIR / name).exists():
        ts = (config.APPLICATIONS_DIR / name).stat().st_mtime
        return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    return store.now()


def delete(name: str) -> None:
    if _db():
        with store.connect() as c:
            c.execute("DELETE FROM cv_files WHERE file_name = ?", (name,))
        return
    (config.APPLICATIONS_DIR / name).unlink(missing_ok=True)
    _meta_path(name).unlink(missing_ok=True)


@contextmanager
def local_path(name: str):
    """A real file path for the parsers. In db mode the bytes go to a temp file that is
    deleted straight after parsing."""
    if not _db():
        yield config.APPLICATIONS_DIR / name
        return
    tmp = Path(tempfile.mkdtemp()) / Path(name).name
    tmp.write_bytes(read(name))
    try:
        yield tmp
    finally:
        tmp.unlink(missing_ok=True)
        tmp.parent.rmdir()
