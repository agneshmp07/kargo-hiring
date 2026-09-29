"""The Vercel set-up: everything in the database (KARGO_STORAGE=db), nothing on disk.
Runs on SQLite here; tests/test_neon_live.py runs the same flow on Neon."""
import zipfile
import io

import pytest

from conftest import IDENTITY, FakeClassifier, write_cv_docx
from shortlister import config, cvstore, decisions, intake, pipeline, privacy, store, vault


@pytest.fixture
def dbenv(env, monkeypatch):
    monkeypatch.setenv("KARGO_STORAGE", "db")
    return env


def _upload(env, name="cv.docx", role="PM", **kw):
    tmp = env / f"_src_{name}"
    write_cv_docx(tmp, **kw)
    saved, msg = intake.save_incoming(name, tmp.read_bytes(), role, source="upload", uploaded_by="meera")
    tmp.unlink()
    return saved


def test_full_flow_without_touching_disk(dbenv):
    name = _upload(dbenv)
    assert name == "PM__cv.docx"
    assert not any((dbenv / "applications").iterdir())  # nothing written to the folder
    assert pipeline.pending_files() == [name]
    s = pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None, limit=1)
    assert s["new"] == 1 and s["remaining"] == 0 and pipeline.pending_files() == []
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["source"] == "upload" and c["uploaded_by"] == "meera"
    assert not (dbenv / "vault" / "identities.json").exists()
    assert vault.get("KG-0001")["email"] == IDENTITY["email"]

    out = decisions.record("KG-0001", "PM", "Advance")
    assert out["email"]["status"] == "dry_run" and out["email"]["outbox_path"] is None
    assert not (dbenv / "outbox").exists()

    data = privacy.backup_bytes()
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert "applications/PM__cv.docx" in names and "vault/identities.bin" in names
    privacy.erase("KG-0001", by="arjun")
    assert cvstore.names() == [] and vault.get("KG-0001") == {}


def test_limit_scores_one_at_a_time(dbenv):
    for i in range(3):
        _upload(dbenv, f"cv{i}.docx")
    fake = FakeClassifier()
    remaining = []
    for _ in range(3):
        remaining.append(pipeline.run_batch(classifier=fake, log=lambda *_: None, limit=1)["remaining"])
    assert remaining == [2, 1, 0] and len(fake.payloads) == 3


def test_vault_must_be_encrypted_on_vercel(dbenv, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    _upload(dbenv)
    with pytest.raises(RuntimeError, match="VAULT_KEY"):
        pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    monkeypatch.setenv("VAULT_KEY", vault.new_key())
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    assert vault.is_encrypted() and vault.get("KG-0001")["name"] == IDENTITY["name"]
    with store.connect_vault() as c:
        raw = c.execute("SELECT data FROM vault_identities").fetchone()["data"]
    assert IDENTITY["email"] not in raw


def test_vault_lives_apart_from_scores(dbenv):
    _upload(dbenv)
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    with store.connect() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "vault_identities" not in tables  # separate database file locally, separate DB on Neon
    assert (dbenv / "data" / "vault.db").exists()


def test_demo_never_uses_the_real_database(monkeypatch):
    from shortlister import store as st

    monkeypatch.setattr(st, "_force_sqlite", False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://real/neon")
    monkeypatch.setenv("KARGO_DEMO", "1")
    assert st.database_url() is None
    monkeypatch.setenv("DEMO_DATABASE_URL", "postgresql://demo/branch")
    assert st.database_url() == "postgresql://demo/branch"
    monkeypatch.delenv("KARGO_DEMO")
    assert st.database_url() == "postgresql://real/neon"


def test_old_database_gets_new_columns(env):
    """A database created by an earlier version is upgraded in place, never dropped."""
    import sqlite3

    from shortlister import store as st

    path = env / "data" / "old.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE candidates (id TEXT PRIMARY KEY, file_name TEXT UNIQUE NOT NULL, file_hash TEXT NOT NULL)")
    old.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, candidate_id TEXT, "
                "role TEXT NOT NULL, decision TEXT NOT NULL)")
    old.execute("INSERT INTO candidates VALUES ('KG-0001', 'a.docx', 'h')")
    old.commit()
    old.close()
    st.set_db_path(path)
    with st.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(decisions)")}
        kept = conn.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()["n"]
    assert {"undone_at", "decided_by", "undone_by"} <= cols and "Pass" not in cols
    assert kept == 1
