"""One deployment, two products: the demo (fictional) and the real product, chosen on the opening screen."""
import pytest
from fastapi.testclient import TestClient

from shortlister import auth, config
from shortlister.server import app

H = {"X-Requested-With": "kargo"}


@pytest.fixture
def both(env, monkeypatch):
    monkeypatch.setenv("KARGO_MODES", "demo,real")
    return TestClient(app)


def choose(client, mode):
    r = client.post("/api/auth/mode", json={"mode": mode}, headers=H)
    assert r.status_code == 200, r.text


def test_opening_screen_offers_both_and_nothing_opens_before_choosing(both):
    s = both.get("/api/auth/state").json()
    assert s["modes"] == ["demo", "real"] and s["mode"] is None and s["has_users"] is None
    assert both.get("/api/board").status_code == 401
    assert both.post("/api/auth/login", json={"username": "a", "password": "b"}).status_code == 409


def test_demo_and_real_are_separate(both):
    choose(both, "demo")
    s = both.get("/api/auth/state").json()
    assert s["mode"] == "demo" and len(s["demo_users"]) == 4
    assert both.post("/api/auth/demo-login", json={"username": "arjun"}).status_code == 200
    assert both.get("/api/auth/me").json()["mode"]["demo"] is True
    choose(both, "real")
    s = both.get("/api/auth/state").json()
    assert s["mode"] == "real" and s["has_users"] is False and s["demo_users"] == []  # demo users aren't here
    assert both.get("/api/board").status_code == 401  # switching signs you out


def test_demo_sign_in_is_rejected_on_the_real_product(both):
    choose(both, "demo")
    both.post("/api/auth/demo-login", json={"username": "arjun"})
    session = both.cookies.get("kargo_session")
    with config.use_mode("real"):
        auth.create_user("arjun", "Real Arjun", "founder", "correct horse 42")
    both.cookies.set("kargo_mode", "real")
    both.cookies.set("kargo_session", session)
    assert both.get("/api/board").status_code == 401


def test_founder_setup_is_protected_on_a_public_deployment(env, monkeypatch):
    monkeypatch.setenv("KARGO_MODES", "demo,real")
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SESSION_SECRET", "x" * 64)  # required on a public deployment
    both = TestClient(app, base_url="https://testserver")  # cookies are HTTPS-only there
    choose(both, "real")
    body = {"name": "Arjun", "username": "arjun", "password": "correct horse 42"}
    assert both.get("/api/auth/state").json()["setup"] == "cli"
    assert both.post("/api/auth/setup", json=body, headers=H).status_code == 403
    monkeypatch.setenv("SETUP_CODE", "kargo-2026-xyz")
    assert both.get("/api/auth/state").json()["setup"] == "code"
    assert both.post("/api/auth/setup", json={**body, "setup_code": "wrong"}, headers=H).status_code == 403
    r = both.post("/api/auth/setup", json={**body, "setup_code": "kargo-2026-xyz"}, headers=H)
    assert r.status_code == 200 and both.get("/api/auth/me").json()["user"]["role"] == "founder"


def test_careers_form_belongs_to_the_real_product(both):
    assert both.get("/api/apply").status_code == 200  # no choice needed for candidates


def test_cron_serves_both_products(both, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s")
    r = both.get("/api/cron/tick", headers={"Authorization": "Bearer s"}).json()
    assert set(r) >= {"demo", "real"} and "error" not in r["demo"] and "error" not in r["real"]
