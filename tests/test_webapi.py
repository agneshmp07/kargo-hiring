"""The JSON API behind the Next.js app."""
import pytest
from fastapi.testclient import TestClient

from conftest import IDENTITY, FakeClassifier, write_cv_docx
from shortlister import auth, pipeline
from shortlister.server import app

H = {"X-Requested-With": "kargo"}


@pytest.fixture
def api(env):
    auth.create_user("arjun", "Arjun Mehta", "founder", "correct horse 42", "arjun@example.com")
    auth.create_user("rahul", "Rahul Verma", "interviewer", "battery staple 7")
    write_cv_docx(env / "applications" / "cv_a_pm.docx")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    return TestClient(app)


def login(client, user="arjun", pw="correct horse 42"):
    r = client.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text


def test_needs_sign_in_and_rejects_bad_password(api):
    assert api.get("/api/board").status_code == 401
    assert api.post("/api/auth/login", json={"username": "arjun", "password": "nope nope 1"}).status_code == 401
    assert api.get("/api/board", cookies={"kargo_session": "forged.token"}).status_code == 401


def test_session_cookie_is_httponly(api):
    r = api.post("/api/auth/login", json={"username": "arjun", "password": "correct horse 42"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_csrf_header_required_for_changes(api):
    login(api)
    r = api.post("/api/decisions", json={"candidate_id": "KG-0001", "role": "PM", "decision": "Hold"})
    assert r.status_code == 403
    r = api.post("/api/decisions", json={"candidate_id": "KG-0001", "role": "PM", "decision": "Hold"}, headers=H)
    assert r.status_code == 200


def test_interviewer_cannot_decide_or_open_settings(api):
    login(api, "rahul", "battery staple 7")
    assert api.get("/api/board").status_code == 200
    r = api.post("/api/decisions", json={"candidate_id": "KG-0001", "role": "PM", "decision": "Advance"}, headers=H)
    assert r.status_code == 403
    assert api.get("/api/settings").status_code == 403
    assert "decide" not in api.get("/api/auth/me").json()["perms"]


def test_name_hidden_until_invited(api):
    login(api)
    card = api.get("/api/board").json()["cards"][0]
    assert card["name"] is None and IDENTITY["name"] not in str(card)
    r = api.post("/api/decisions", json={"candidate_id": "KG-0001", "role": "PM", "decision": "Advance"}, headers=H)
    assert r.json()["name"] == IDENTITY["name"]
    card = api.get("/api/board").json()["cards"][0]
    assert card["name"] == IDENTITY["name"] and card["decision"]["decision"] == "Advance"


def test_upload_then_score_one_at_a_time(api, env, monkeypatch):
    login(api)
    from shortlister import webapi

    monkeypatch.setattr(webapi, "_standin", lambda: True)  # keyword stand-in scorer: no API key needed
    auth.create_user("meera", "Meera", "coordinator", None)
    tmp = env / "src.docx"
    write_cv_docx(tmp, body=["Senior Product Manager · Railyard (Series A) · Jan 2020 – Present",
                             "Owned the carrier integrations platform, reporting to the CTO."])
    files = [("files", ("New CV.docx", tmp.read_bytes()))]
    r = api.post("/api/cvs/upload", data={"role": "SPM"}, files=files, headers=H)
    assert r.json()["saved"] == ["SPM__New CV.docx"]
    assert api.get("/api/cvs/pending").json()["pending"] == ["SPM__New CV.docx"]
    r = api.post("/api/cvs/score-next", headers=H).json()
    assert r["scored"] == ["KG-0002"] and r["remaining"] == 0


def test_cron_needs_secret(api, monkeypatch):
    assert api.get("/api/cron/tick").status_code == 401
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert api.get("/api/cron/tick", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = api.get("/api/cron/tick", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200 and r.json()["ok"]


def test_first_run_setup_only_once(env):
    client = TestClient(app)
    assert client.get("/api/auth/state").json()["has_users"] is False
    r = client.post("/api/auth/setup", json={"name": "Arjun", "username": "arjun", "email": "a@x.com",
                                             "password": "correct horse 42"})
    assert r.status_code == 200 and client.get("/api/auth/me").json()["user"]["role"] == "founder"
    r = client.post("/api/auth/setup", json={"name": "X", "username": "x", "password": "correct horse 42"})
    assert r.status_code == 409


def test_settings_roundtrip_and_template_guard(api):
    login(api)
    s = api.get("/api/settings").json()
    assert s["settings"]["undo_minutes"] == 0 and s["vault"]["location"]
    assert api.post("/api/settings", json={"undo_minutes": 5}, headers=H).status_code == 200
    assert api.get("/api/settings").json()["settings"]["undo_minutes"] == 5
    r = api.post("/api/templates/check", json={"subject": "Hi", "body": "Your score is 40"}, headers=H).json()
    assert r["errors"]
    r = api.post("/api/templates/check", json={"subject": "Hi {first_name}", "body": "Thanks"}, headers=H).json()
    assert r["preview"]["subject"] == "Hi Asha"
