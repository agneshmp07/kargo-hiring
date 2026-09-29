"""Pipeline behaviour: idempotency, parse failures, cross-role scoring, logging."""
import json

from conftest import FakeClassifier, good_classification, write_cv_docx
from shortlister import decisions, llm, pipeline, store


def test_unchanged_files_are_not_rescored(env):
    write_cv_docx(env / "applications" / "cv_a_pm.docx")
    fake = FakeClassifier()
    pipeline.run_batch(classifier=fake, log=lambda *_: None)
    s = pipeline.run_batch(classifier=fake, log=lambda *_: None)
    assert len(fake.payloads) == 1 and s["skipped_unchanged"] == 1


def test_parse_failure_is_low_confidence_borderline(env):
    (env / "applications" / "broken_pm.pdf").write_bytes(b"not really a pdf")
    fake = FakeClassifier()
    s = pipeline.run_batch(classifier=fake, log=lambda *_: None)
    assert s["parse_failures"] == 1 and fake.payloads == []
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["confidence"] == "low"
    assert c["results_json"]["PM"]["band"] == "Borderline"
    assert "low-confidence floor" in c["results_json"]["PM"]["floors"]


def test_invalid_output_retried_once_then_low_confidence(env):
    class BadClient:
        calls = 0

        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                BadClient.calls += 1

                class Block:
                    type = "text"
                    text = "{not json"

                class R:
                    stop_reason = "end_turn"
                    content = [Block()]
                return R()

    write_cv_docx(env / "applications" / "cv_a_pm.docx")
    pipeline.run_batch(classifier=lambda p: llm.classify(p, BadClient), log=lambda *_: None)
    assert BadClient.calls == 2
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["confidence"] == "low" and c["results_json"]["PM"]["band"] == "Borderline"


def test_spm_applicant_with_pm_years_is_scored_for_both(env):
    write_cv_docx(env / "applications" / "cv_b_spm.docx", role_line="Applying for: Senior Product Manager")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)  # pm_years 3.3
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["applied_role"] == "SPM" and set(c["results_json"]) == {"SPM", "PM"}
    assert c["better_fit"] == "PM"


def test_unclear_role_scored_for_both(env):
    write_cv_docx(env / "applications" / "resume.docx", role_line="Hello")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["applied_role"] is None and set(c["results_json"]) == {"PM", "SPM"}


def test_decision_log_records_what_arjun_saw(env):
    write_cv_docx(env / "applications" / "cv_a_pm.docx")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)
    decisions.record("KG-0001", "PM", "Hold")
    lines = [json.loads(l) for l in (store.db_path().parent / "decision_log.jsonl").read_text().splitlines()]
    d = [l for l in lines if l["event"] == "decision"][0]
    for k in ("ts", "candidate_id", "role", "band", "final", "rationale_shown", "decision"):
        assert d[k] not in (None, "")


def test_prompt_contains_anchors_verbatim():
    prompt = llm.build_system_prompt({"PM": "jd pm", "SPM": "jd spm"})
    assert llm.ANCHORS in prompt
    assert '"integrated with Delhivery APIs" earns N1 = 1, not P1' in prompt


def test_sonnet5_payload_has_no_temperature_but_older_models_get_zero():
    p = llm.build_payload("KG-1", "text", "PM", "sys", model="claude-sonnet-5")
    assert "temperature" not in p
    p = llm.build_payload("KG-1", "text", "PM", "sys", model="claude-haiku-4-5")
    assert p["temperature"] == 0


def test_postgres_dialect_translation():
    from shortlister.store import _to_pg

    assert _to_pg("SELECT * FROM x WHERE id = ?") == "SELECT * FROM x WHERE id = %s"
    assert _to_pg("INSERT OR IGNORE INTO t (a) VALUES (?)") == "INSERT INTO t (a) VALUES (%s) ON CONFLICT DO NOTHING"


def test_database_url_selects_postgres_backend(monkeypatch):
    from shortlister import store

    monkeypatch.setattr(store, "_force_sqlite", False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-x.neon.tech/db?sslmode=require")
    assert store.backend() == "postgres"
    monkeypatch.delenv("DATABASE_URL")
    assert store.backend() == "sqlite"


def test_postgres_ignore_goes_before_returning():
    from shortlister.store import _to_pg

    assert _to_pg("INSERT OR IGNORE INTO t (a) VALUES (?) RETURNING id") == \
        "INSERT INTO t (a) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id"
