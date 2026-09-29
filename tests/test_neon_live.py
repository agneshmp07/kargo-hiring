"""Optional: runs the decision/email flow against a real Neon/Postgres database.
Skipped unless TEST_DATABASE_URL is set. Uses its own throwaway tables' rows only."""
import os

import pytest

from conftest import FakeClassifier, write_cv_docx
from shortlister import decisions, pipeline, store

URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")
def test_flow_on_postgres(env, monkeypatch):
    monkeypatch.setattr(store, "_force_sqlite", False)
    monkeypatch.setenv("DATABASE_URL", URL)
    assert store.backend() == "postgres"
    write_cv_docx(env / "applications" / "cv_neon_pm.docx")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    with store.connect() as conn:
        cid = store.candidate_by_file(conn, "cv_neon_pm.docx")["id"]
    out = decisions.record(cid, "PM", "Pass")
    assert out["email"]["status"] == "dry_run"
