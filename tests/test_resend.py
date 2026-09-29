"""Resend integration: request shape, idempotency, retries, webhooks, domain check, test email."""
import json

import pytest

from conftest import FakeClassifier, write_cv_docx
from shortlister import decisions, emails, pipeline, resend_client, store


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeHTTP:
    """Stands in for requests: returns queued responses and records every call."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0) if self.responses else Resp(200, {"id": "em_default"})

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        return self.responses.pop(0)


@pytest.fixture
def live(env, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("RESEND_API_KEY", "re_live_key_abcdefghijklmnop")
    monkeypatch.setenv("FROM_EMAIL", "Kargo Hiring <hiring@kargo.in>")
    monkeypatch.setenv("REPLY_TO", "arjun@kargo.in")
    return env


def test_request_shape(live):
    http = FakeHTTP(Resp(200, {"id": "em_1"}))
    pid = resend_client.send(to="a@b.com", subject="Hi", text="Hello there\n\nBook: https://cal.com/x",
                             idempotency_key="kargo-email-7", tags={"kind": "invite", "candidate": "KG-0001"},
                             session=http)
    c = http.calls[0]
    assert pid == "em_1" and c["url"] == "https://api.resend.com/emails"
    assert c["headers"]["User-Agent"].startswith("kargo-hiring/")  # Resend 403s without one
    assert c["headers"]["Idempotency-Key"] == "kargo-email-7"
    assert c["headers"]["Authorization"] == "Bearer re_live_key_abcdefghijklmnop"
    body = c["json"]
    assert body["from"] == "Kargo Hiring <hiring@kargo.in>" and body["to"] == ["a@b.com"]
    assert body["reply_to"] == "arjun@kargo.in" and body["text"].startswith("Hello there")
    assert '<a href="https://cal.com/x"' in body["html"]
    assert {"name": "candidate", "value": "KG-0001"} in body["tags"]


def test_rate_limit_is_retried_but_bad_request_is_not(live):
    slept = []
    http = FakeHTTP(Resp(429, {"message": "slow down"}, {"retry-after": "1"}), Resp(200, {"id": "em_2"}))
    assert resend_client.send(to="a@b.com", subject="s", text="t", session=http, sleep=slept.append) == "em_2"
    assert slept == [1.0] and len(http.calls) == 2
    http = FakeHTTP(Resp(422, {"message": "Invalid `to` field"}))
    with pytest.raises(resend_client.ResendError, match="Invalid"):
        resend_client.send(to="bad", subject="s", text="t", session=http, sleep=slept.append)
    assert len(http.calls) == 1


def _pass_decision(env):
    write_cv_docx(env / "applications" / "cv_a_pm.docx")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)


def test_every_attempt_uses_the_same_idempotency_key(live, monkeypatch):
    import requests

    http = FakeHTTP(Resp(500), Resp(500), Resp(500), Resp(200, {"id": "em_3"}))
    monkeypatch.setattr(requests, "post", http.post)
    monkeypatch.setattr(resend_client.time, "sleep", lambda *_: None)
    _pass_decision(live)
    out = decisions.record("KG-0001", "PM", "Pass")
    keys = {c["headers"]["Idempotency-Key"] for c in http.calls}
    assert out["email"]["status"] == "sent" and out["email"]["provider_id"] == "em_3"
    assert keys == {f"kargo-email-{out['email']['id']}"}  # safe to retry: Resend sends it once
    assert out["email"]["attempts"] == 2


def test_a_sent_email_is_never_sent_again(live, monkeypatch):
    import requests

    http = FakeHTTP()
    monkeypatch.setattr(requests, "post", http.post)
    _pass_decision(live)
    out = decisions.record("KG-0001", "PM", "Pass")
    emails.deliver(out["email"]["id"])  # e.g. the cron job picks it up again
    emails.send_due()
    assert len(http.calls) == 1


def test_api_key_never_stored(live, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "post", FakeHTTP(Resp(401, {"message": "API key is invalid"}),
                                                   Resp(401, {"message": "API key is invalid"})).post)
    _pass_decision(live)
    out = decisions.record("KG-0001", "PM", "Pass")
    assert out["email"]["status"] == "failed" and "invalid" in out["email"]["error"]
    with store.connect() as conn:
        dump = json.dumps(store.rows(conn, "SELECT * FROM emails") + store.rows(conn, "SELECT * FROM audit_log"))
    assert "re_live_key" not in dump


def test_webhook_events_never_downgrade(env):
    _pass_decision(env)
    out = decisions.record("KG-0001", "PM", "Pass")
    with store.connect() as conn:
        conn.execute("UPDATE emails SET provider_id = 'em_9', status = 'sent'")
    emails.apply_provider_event("em_9", "email.bounced", "Permanent General: mailbox does not exist")
    emails.apply_provider_event("em_9", "email.delivered")  # arrives late, out of order
    with store.connect() as conn:
        e = store.one(conn, "SELECT status, error FROM emails WHERE id = ?", (out["email"]["id"],))
    assert e["status"] == "bounced" and "does not exist" in e["error"]
    assert resend_client.new_status("sent", "email.delivered") == "delivered"
    assert resend_client.new_status("cancelled", "email.delivered") == "cancelled"
    evt = {"data": {"bounce": {"type": "Permanent", "subType": "Suppressed", "message": "on the suppression list"}}}
    assert "Suppressed" in resend_client.event_detail(evt)


def test_domain_status(live):
    ok = FakeHTTP(Resp(200, {"data": [{"name": "kargo.in", "status": "verified", "region": "ap-northeast-1"}]}))
    assert resend_client.domain_status(ok)["ok"] is True
    pending = FakeHTTP(Resp(200, {"data": [{"name": "kargo.in", "status": "pending"}]}))
    assert resend_client.domain_status(pending)["ok"] is False
    missing = FakeHTTP(Resp(200, {"data": [{"name": "other.com", "status": "verified"}]}))
    assert resend_client.domain_status(missing)["state"] == "not_added"
    restricted = FakeHTTP(Resp(401, {"message": "restricted"}))
    assert resend_client.domain_status(restricted)["state"] == "restricted_key"


def test_test_email_endpoint(live, monkeypatch):
    import requests
    from fastapi.testclient import TestClient

    from shortlister import auth
    from shortlister.server import app

    http = FakeHTTP(Resp(200, {"id": "em_test"}))
    monkeypatch.setattr(requests, "post", http.post)
    auth.create_user("arjun", "Arjun", "founder", "correct horse 42", "arjun@kargo.in")
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "arjun", "password": "correct horse 42"})
    r = client.post("/api/resend/test", json={}, headers={"X-Requested-With": "kargo"})
    assert r.status_code == 200 and r.json()["to"] == "arjun@kargo.in"
    assert http.calls[0]["json"]["to"] == ["arjun@kargo.in"] and "test" in http.calls[0]["json"]["subject"]
    monkeypatch.setenv("KARGO_DEMO", "1")
    assert client.post("/api/resend/test", json={}, headers={"X-Requested-With": "kargo"}).status_code in (400, 401)
