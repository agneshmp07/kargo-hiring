"""Acceptance test 5: the default configuration sends nothing."""
import json

import pytest

from conftest import FakeClassifier, write_cv_docx
from shortlister import config, decisions, pipeline, store


@pytest.fixture
def scored(env):
    write_cv_docx(env / "applications" / "cv_x_pm.docx")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    return env


def test_default_is_dry_run(scored, monkeypatch):
    import requests

    def boom(*a, **k):
        raise AssertionError("network send attempted in default config")

    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_should_never_be_used_123")
    assert config.dry_run() is True

    out = decisions.record("KG-0001", "PM", "Advance")
    assert out["email"]["status"] == "dry_run"
    files = list((scored / "outbox").glob("*.json"))
    assert len(files) == 1
    msg = json.loads(files[0].read_text(encoding="utf-8"))
    assert msg["dry_run"] is True and "Product Manager" in msg["subject"]


def test_only_explicit_false_enables_sending(monkeypatch):
    for val, expected in [(None, True), ("", True), ("true", True), ("yes", True), ("FALSE", False), ("false", False)]:
        if val is None:
            monkeypatch.delenv("DRY_RUN", raising=False)
        else:
            monkeypatch.setenv("DRY_RUN", val)
        assert config.dry_run() is expected, val


def test_live_mode_uses_test_recipient_and_retries_once(scored, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TEST_RECIPIENT", "arjun-test@example.com")
    calls = []

    def flaky(to, subject, body):
        calls.append(to)
        raise RuntimeError("503 from provider")

    out = decisions.record("KG-0001", "PM", "Pass", sender=flaky)
    assert calls == ["arjun-test@example.com", "arjun-test@example.com"]  # first try + one retry
    assert out["email"]["status"] == "failed" and out["email"]["attempts"] == 2
    assert not list((scored / "outbox").glob("*.json"))


def test_api_key_never_logged(scored, monkeypatch):
    key = "re_SECRETKEY_abcdefghijklmnop"
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", key)
    monkeypatch.setenv("TEST_RECIPIENT", "arjun-test@example.com")

    def leaky(to, subject, body):
        raise RuntimeError(f"auth failed for {key}")

    out = decisions.record("KG-0001", "PM", "Pass", sender=leaky)
    assert key not in (out["email"]["error"] or "")
    log = (store.db_path().parent / "decision_log.jsonl").read_text(encoding="utf-8")
    assert key not in log


def test_live_invite_refused_without_scheduling_link(scored, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    sent = []
    out = decisions.record("KG-0001", "PM", "Advance", sender=lambda **k: sent.append(k))
    assert sent == [] and out["email"]["status"] == "failed"
    assert "SCHEDULING_LINK" in out["email"]["error"]
