"""Organisation features: undo, permissions, templates, automation, intake, privacy, versions, analytics."""
import base64
import hashlib
import hmac
import json
import time
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from conftest import FakeClassifier, good_classification, write_cv_docx
from shortlister import (analytics, auth, automation, config, decisions, emails, intake, pipeline, privacy, settings,
                         store, vault, versions)


def _scored(env, n=1, **kw):
    for i in range(n):
        write_cv_docx(env / "applications" / f"cv_{i}_pm.docx", **kw)
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)


def _emails():
    with store.connect() as conn:
        return store.emails(conn)


# ---------------------------------------------------------------- undo window

def test_undo_window_holds_email_and_undo_cancels_it(env):
    _scored(env)
    settings.put("undo_minutes", 10, "t")
    out = decisions.record("KG-0001", "PM", "Advance", by="arjun")
    assert out["email"]["status"] == "scheduled"
    assert not (env / "outbox").exists() or not list((env / "outbox").glob("*.json"))
    decisions.undo(out["decision_id"], by="arjun")
    assert _emails()[0]["status"] == "cancelled"
    with store.connect() as conn:
        assert store.latest_decision(conn, "KG-0001") is None
        assert conn.execute("SELECT 1 FROM stages WHERE candidate_id = 'KG-0001'").fetchone() is None
    # the candidate can be decided again, and the cancelled email never goes out
    decisions.record("KG-0001", "PM", "Pass", by="arjun")
    emails.send_due(now=datetime.now(timezone.utc) + timedelta(minutes=11))
    statuses = sorted((e["kind"], e["status"]) for e in _emails())
    assert statuses == [("invite", "cancelled"), ("rejection", "dry_run")]


def test_too_late_to_undo_after_send(env):
    _scored(env)
    settings.put("undo_minutes", 10, "t")
    out = decisions.record("KG-0001", "PM", "Pass", by="arjun")
    emails.send_due(now=datetime.now(timezone.utc) + timedelta(minutes=11))
    with pytest.raises(decisions.DecisionError, match="too late"):
        decisions.undo(out["decision_id"], by="arjun")


def test_undone_decision_cannot_create_email(env):
    _scored(env)
    settings.put("undo_minutes", 10, "t")
    out = decisions.record("KG-0001", "PM", "Pass")
    decisions.undo(out["decision_id"])
    with pytest.raises(emails.NoDecisionError):
        emails.dispatch(out["decision_id"])


# ---------------------------------------------------------------- logins & permissions

def test_passwords_hashed_and_checked(env):
    auth.create_user("arjun", "Arjun Mehta", "founder", "correct horse 42", "a@example.com")
    with store.connect() as conn:
        stored = conn.execute("SELECT pw_hash FROM users").fetchone()["pw_hash"]
    assert "correct horse" not in stored and stored.startswith("scrypt$")
    assert auth.authenticate("arjun", "correct horse 42")["role"] == "founder"
    assert auth.authenticate("arjun", "wrong password 1") is None
    with pytest.raises(ValueError):
        auth.create_user("bob", "Bob", "viewer", "short")


def test_only_decision_roles_can_decide(env):
    founder = {"username": "a", "role": "founder"}
    manager = {"username": "b", "role": "hiring_manager"}
    assert auth.can(founder, "decide") and not auth.can(manager, "decide")
    settings.put("decision_roles", ["founder", "hiring_manager"], "t")
    assert auth.can(manager, "decide")
    assert not auth.can({"username": "c", "role": "viewer"}, "comment")


# ---------------------------------------------------------------- templates

def test_template_guardrails_and_override(env):
    assert emails.validate_template("Hi", "Your score was 40")
    assert emails.validate_template("Hi {nme}", "x")
    assert emails.validate_template("Hi", "We are pleased to offer you")
    emails.save_template("rejection", "PM", "Update on {role_name}", "Hi {first_name}, thanks for applying.", "t")
    s, b = emails.render("rejection", "PM", {"name": "Asha K"}, "KG-1")
    assert s == "Update on Product Manager" and b.startswith("Hi Asha")
    with pytest.raises(ValueError):
        emails.save_template("invite", "*", "Hi", "Your band is Strong", "t")


def test_booking_link_carries_only_the_candidate_id(env, monkeypatch):
    monkeypatch.setenv("SCHEDULING_LINK", "https://cal.com/kargo/interview")
    link = emails.personalized_link("PM", "KG-0007")
    assert "KG-0007" in link and "@" not in link
    monkeypatch.setenv("SCHEDULING_LINK_SPM", "https://calendly.com/kargo/spm")
    assert emails.personalized_link("SPM", "KG-0008").endswith("utm_content=KG-0008")


# ---------------------------------------------------------------- automation after an invite

def test_followup_then_reminder_then_post_interview(env):
    _scored(env)
    out = decisions.record("KG-0001", "PM", "Advance", by="arjun")
    now = datetime.now(timezone.utc)
    assert automation.followups(now) == 0  # too soon
    assert automation.followups(now + timedelta(days=4)) == 1
    assert automation.followups(now + timedelta(days=5)) == 0  # only once
    start = (now + timedelta(hours=10)).isoformat(timespec="minutes")
    decisions.set_stage("KG-0001", "scheduled", "cal.com webhook", scheduled_for=start)
    assert automation.interview_reminders(now) == 1
    assert automation.interview_reminders(now) == 0
    decisions.set_stage("KG-0001", "not_selected", "arjun")
    kinds = [e["kind"] for e in _emails()]
    assert sorted(kinds) == ["followup", "interview_reminder", "invite", "post_interview_rejection"]
    assert all(e["decision_id"] == out["decision_id"] for e in _emails())


def test_selected_sends_nothing_and_post_interview_needs_outcome(env):
    _scored(env)
    out = decisions.record("KG-0001", "PM", "Advance")
    with pytest.raises(emails.NoDecisionError):
        emails.queue_followup_message("post_interview_rejection", out["decision_id"])
    decisions.set_stage("KG-0001", "selected", "arjun")
    assert [e["kind"] for e in _emails()] == ["invite"]
    assert not any("offer" in (e["body"] or "").lower() for e in _emails())


def test_ack_is_off_by_default(env):
    _scored(env)
    assert _emails() == []
    with pytest.raises(emails.NoDecisionError):
        emails.queue_ack("KG-0001")
    settings.put("ack_enabled", True, "t")
    write_cv_docx(env / "applications" / "cv_new_pm.docx", body=["Product Manager · X · Jan 2022 – Present",
                                                                 "Sole PM reporting to the CEO."])
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    assert [e["kind"] for e in _emails()] == ["ack"]


def test_whatsapp_only_for_opted_in_candidates(env):
    settings.put("whatsapp_enabled", True, "t")
    write_cv_docx(env / "applications" / "PM__opted.docx")
    pipeline.write_meta("PM__opted.docx", source="careers", whatsapp_opt_in=True)
    write_cv_docx(env / "applications" / "PM__not_opted.docx")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    decisions.record("KG-0001", "PM", "Advance")
    decisions.record("KG-0002", "PM", "Advance")
    wa = [e for e in _emails() if e["channel"] == "whatsapp"]
    with store.connect() as conn:
        opted = conn.execute("SELECT id FROM candidates WHERE whatsapp_opt_in = 1").fetchone()["id"]
    assert [e["candidate_id"] for e in wa] == [opted]


def test_digest_and_hold_reminder_go_to_the_team(env):
    auth.create_user("arjun", "Arjun", "founder", "correct horse 42", "arjun@example.com")
    _scored(env)
    decisions.record("KG-0001", "PM", "Hold")
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert automation.hold_reminder_email(later)
    assert automation.daily_digest(later, force=True)
    internal = [e for e in _emails() if e["purpose"] == "internal"]
    assert {e["kind"] for e in internal} == {"hold_reminder", "digest"}
    assert all(e["to_addr"] == "arjun@example.com" for e in internal)


# ---------------------------------------------------------------- intake, webhooks, careers form

def test_careers_form_requires_consent_and_records_source(env):
    from fastapi.testclient import TestClient

    from shortlister.server import app

    client = TestClient(app)
    buf = (env / "x.docx")
    write_cv_docx(buf)
    r = client.post("/api/apply", data={"role": "PM"}, files={"cv": ("x.docx", buf.read_bytes())})
    assert r.status_code == 400
    r = client.post("/api/apply", data={"role": "PM", "consent": "yes", "whatsapp": "yes"},
                    files={"cv": ("My CV.docx", buf.read_bytes())})
    assert r.status_code == 200 and "Thank you" in r.text
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["source"] == "careers" and c["whatsapp_opt_in"] == 1 and c["applied_role"] == "PM"
    assert client.get("/api/privacy").status_code == 200


def test_webhooks_reject_bad_signatures_and_track_bookings(env, monkeypatch):
    from fastapi.testclient import TestClient

    from shortlister.server import app

    _scored(env)
    decisions.record("KG-0001", "PM", "Advance")
    client = TestClient(app)
    monkeypatch.setenv("CALCOM_WEBHOOK_SECRET", "calsecret")
    body = json.dumps({"triggerEvent": "BOOKING_CREATED", "payload": {
        "uid": "b1", "startTime": "2026-10-02T05:30:00Z", "metadata": {"candidate_id": "KG-0001"}}}).encode()
    assert client.post("/api/webhooks/calcom", content=body, headers={"x-cal-signature-256": "nope"}).status_code == 401
    sig = hmac.new(b"calsecret", body, hashlib.sha256).hexdigest()
    r = client.post("/api/webhooks/calcom", content=body, headers={"x-cal-signature-256": sig})
    assert r.json()["matched"] is True
    with store.connect() as conn:
        st = store.one(conn, "SELECT * FROM stages WHERE candidate_id = 'KG-0001'")
    assert st["stage"] == "scheduled" and st["scheduled_for"].startswith("2026-10-02")

    # Resend bounce, signed the Svix way
    secret = "whsec_" + base64.b64encode(b"resend-secret-key").decode()
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", secret)
    with store.connect() as conn:
        conn.execute("UPDATE emails SET provider_id = 'em_1'")
    body = json.dumps({"type": "email.bounced", "data": {"email_id": "em_1"}}).encode()
    ts = str(int(time.time()))
    s = base64.b64encode(hmac.new(b"resend-secret-key", f"m1.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    assert client.post("/api/webhooks/resend", content=body, headers={
        "svix-id": "m1", "svix-timestamp": ts, "svix-signature": "v1,bad"}).status_code == 401
    assert client.post("/api/webhooks/resend", content=body, headers={
        "svix-id": "m1", "svix-timestamp": ts, "svix-signature": f"v1,{s}"}).status_code == 200
    assert _emails()[0]["status"] == "bounced"


def test_duplicates_flagged_and_upload_dedupes(env):
    _scored(env, 2)
    with store.connect() as conn:
        assert store.get_candidate(conn, "KG-0002")["duplicate_of"] == "KG-0001"
    data = (env / "applications" / "cv_0_pm.docx").read_bytes()
    name, msg = intake.save_incoming("again.docx", data, "PM")
    assert name is None and "already received" in msg
    name, msg = intake.save_incoming("../../evil.exe", b"x")
    assert name is None


# ---------------------------------------------------------------- privacy

def test_erase_and_export(env):
    _scored(env)
    decisions.record("KG-0001", "PM", "Pass")
    decisions.add_comment("KG-0001", "priya", "Nice ops story")
    assert privacy.export("KG-0001")["identity"]["email"]
    privacy.erase("KG-0001", by="arjun")
    assert vault.get("KG-0001") == {}
    assert not (env / "applications" / "cv_0_pm.docx").exists()
    with store.connect() as conn:
        c = store.one(conn, "SELECT * FROM candidates WHERE id = 'KG-0001'")
        assert c["redacted_text"] is None and c["erased_at"]
        assert conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 1  # audit trail kept
        assert conn.execute("SELECT body FROM comments").fetchone()["body"] == "[erased]"
        assert conn.execute("SELECT body FROM emails").fetchone()["body"] == "[erased]"


def test_retention_purges_old_final_outcomes_only(env):
    _scored(env, 2)
    decisions.record("KG-0001", "PM", "Pass")
    decisions.record("KG-0002", "PM", "Hold")
    later = datetime.now(timezone.utc) + timedelta(days=181)
    assert privacy.purge_expired(later) == ["KG-0001"]


def test_vault_encryption(env, monkeypatch):
    monkeypatch.setenv("VAULT_KEY", vault.new_key())
    _scored(env)
    assert vault.is_encrypted()
    assert b"priya" not in vault.VAULT_FILE.read_bytes().lower()
    assert vault.get("KG-0001")["email"]
    monkeypatch.delenv("VAULT_KEY")
    assert vault.get("KG-0001") == {}  # unreadable without the key


def test_backup_contains_tables(env):
    _scored(env)
    p = privacy.backup()
    names = zipfile.ZipFile(p).namelist()
    assert "db/candidates.json" in names and "db/decisions.json" in names


# ---------------------------------------------------------------- versions & roles

def test_publish_new_role_and_recalculate(env):
    _scored(env)
    p = versions.active()
    assert p["_version"] == 1
    bad = json.loads(json.dumps(p))
    bad["layer_b"]["OPS"] = {"weights": {"ops_lead": 60}, "gate_years_pm": [0, 3]}
    bad["_roles"]["OPS"] = {"name": "Ops PM", "jd_text": "", "definitions": {"ops_lead": "led ops"}}
    assert any("not 100" in e for e in versions.validate(bad))
    bad["layer_b"]["OPS"]["weights"] = {"ops_lead": 100}
    v = versions.publish(bad, "add ops role", "arjun")
    new = versions.active()
    assert v == 2 and "OPS" in versions.role_codes(new)
    from shortlister import llm

    prompt = llm.build_system_prompt(versions.jd_texts(new), new)
    assert "`ops_lead`: led ops" in prompt and llm.ANCHORS_A in prompt
    out = versions.recalculate_all("arjun")
    assert out["recalculated"] == 1 and any(s.endswith(":OPS") for s in out["skipped_roles"])
    versions.activate(1, "arjun")
    assert versions.active()["_version"] == 1


# ---------------------------------------------------------------- batch API & cost

def test_batch_api_mode(env):
    class Msg:
        def __init__(self, text):
            self.stop_reason = "end_turn"
            self.content = [type("B", (), {"type": "text", "text": text})()]
            self.usage = type("U", (), {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 0,
                                        "cache_creation_input_tokens": 0})()

    class Batches:
        def create(self, requests):
            self.reqs = requests
            return type("Bt", (), {"id": "b1", "processing_status": "in_progress"})()

        def retrieve(self, bid):
            return type("Bt", (), {"id": bid, "processing_status": "ended"})()

        def results(self, bid):
            for r in self.reqs:
                obj = good_classification(r["params"])
                yield type("R", (), {"custom_id": r["custom_id"], "result": type("X", (), {
                    "type": "succeeded", "message": Msg(json.dumps(obj))})()})()

    client = type("C", (), {"messages": type("M", (), {"batches": Batches()})()})()
    for i in range(3):
        write_cv_docx(env / "applications" / f"cv_{i}_pm.docx")
    s = pipeline.run_batch(use_batch_api=True, batch_client=client, log=lambda *_: None)
    assert s["new"] == 3
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0002")
    # 1000 in @ $2/M + 500 out @ $10/M = $0.007, halved for the Batch API
    assert c["usage_json"]["cost_usd"] == pytest.approx(0.0035)
    assert c["results_json"]["PM"]["band"] == "Strong"


# ---------------------------------------------------------------- analytics & calibration

def test_analytics_and_report(env):
    _scored(env, 3)
    decisions.record("KG-0001", "PM", "Advance")
    decisions.record("KG-0002", "PM", "Pass")
    f = dict(analytics.funnel())
    assert f["CVs scored"] == 3 and f["Invited"] == 1
    a = analytics.agreement()
    assert a["decided"] == 2 and a["agreement_%"] == 50  # Pass on a Strong disagrees
    assert analytics.report_pdf()[:4] == b"%PDF"
    assert analytics.training_export_csv().splitlines()[0].startswith("candidate_id,role,pm_years,P1")
    assert analytics.fairness_by_city(min_group=1)[0]["city"] == "Mumbai"


def test_calibration_verdict(env):
    _scored(env, 10)
    for c in analytics.calibration_queue("arjun", 10):
        analytics.rate(c["id"], "arjun", "PM", "Strong")
    s = analytics.calibration_summary("arjun")
    assert s["rated"] == 10 and s["agreement_%"] == 100 and "Good match" in s["verdict"]


def test_demo_keyword_standin_scores_samples(env):
    from shortlister import demo

    demo.SAMPLES_DIR = env / "applications"
    demo.write_samples()
    (env / "applications" / "README.txt").unlink()
    pipeline.run_batch(classifier=demo.keyword_classifier, log=lambda *_: None)
    with store.connect() as conn:
        bands = {c["file_name"]: c["results_json"][pipeline.primary_role(c)]["band"] for c in store.all_candidates(conn)}
    assert bands["Rhea_Kapoor_CV.docx"] == "Strong"
    assert bands["Arnav_Mehra_Resume.docx"] == "Not a fit"  # the keyword trap
    assert bands["Tanvi_Shah.docx"] == "Borderline"         # sparse: low-confidence floor
    assert bands["Vikrant_Rao_SeniorPM.docx"] == "Borderline"  # over the range, kept by the P1 floor


def test_demo_never_sends(monkeypatch):
    monkeypatch.setenv("KARGO_DEMO", "1")
    monkeypatch.setenv("DRY_RUN", "false")
    assert config.dry_run() is True
