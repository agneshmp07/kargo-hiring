"""Acceptance test 4: no email is created without a logged Arjun decision."""
import pytest

from conftest import FakeClassifier, write_cv_docx
from shortlister import decisions, emails, pipeline, store


def _emails():
    with store.connect() as conn:
        return store.emails(conn)


def _scored(env, n=2):
    for i in range(n):
        write_cv_docx(env / "applications" / f"cv_{i}_pm.docx")
    pipeline.run_batch(classifier=FakeClassifier(), log=lambda *_: None)


def test_batch_creates_no_email(env):
    _scored(env)
    assert _emails() == []
    assert not (env / "outbox").exists() or not any((env / "outbox").iterdir())


def test_dispatch_without_decision_is_refused(env):
    _scored(env, 1)
    with pytest.raises(emails.NoDecisionError):
        emails.dispatch(12345)
    assert _emails() == []


def test_every_email_maps_to_a_logged_decision(env):
    _scored(env, 3)
    decisions.record("KG-0001", "PM", "Advance")
    decisions.record("KG-0002", "PM", "Pass")
    decisions.record("KG-0003", "PM", "Hold")
    mails = _emails()
    assert len(mails) == 2  # Hold sends nothing
    with store.connect() as conn:
        for m in mails:
            d = conn.execute("SELECT * FROM decisions WHERE id = ?", (m["decision_id"],)).fetchone()
            assert d is not None and d["candidate_id"] == m["candidate_id"]
            assert d["decision"] in ("Advance", "Pass")
    kinds = {m["candidate_id"]: m["kind"] for m in mails}
    assert kinds == {"KG-0001": "invite", "KG-0002": "rejection"}


def test_exactly_one_email_per_decision(env):
    _scored(env, 1)
    out = decisions.record("KG-0001", "PM", "Pass")
    emails.dispatch(out["decision_id"])  # a second dispatch must not create another
    assert len(_emails()) == 1
    with pytest.raises(decisions.DecisionError):
        decisions.record("KG-0001", "PM", "Advance")  # final decisions can't be re-sent


def test_rejection_has_no_score_or_reason_codes(env):
    _scored(env, 1)
    decisions.record("KG-0001", "PM", "Pass")
    body = _emails()[0]["body"]
    for banned in ("score", "band", "Not a fit", "P1", "Layer", "gate", "Borderline"):
        assert banned not in body
    assert "Product Manager" in body


def test_invite_keeps_scheduling_placeholder(env):
    _scored(env, 1)
    decisions.record("KG-0001", "PM", "Advance")
    assert "{{SCHEDULING_LINK}}" in _emails()[0]["body"]


def test_bulk_pass_skips_open_spot_checks(env):
    def naf(payload):
        from conftest import good_classification
        obj = good_classification(payload)
        for v in obj["layer_a"].values():
            v.update(code=0, evidence=None)
        for r in obj["layer_b"].values():
            for v in r.values():
                v.update(code=0, evidence=None)
        return obj

    for i in range(5):
        write_cv_docx(env / "applications" / f"cv_{i}_pm.docx")
    summary = pipeline.run_batch(classifier=FakeClassifier(naf), log=lambda *_: None, seed=1)
    assert len(summary["spot_checks"]) == 3
    ids = decisions.bulk_pass_candidates("PM")
    assert len(ids) == 2 and not set(ids) & set(summary["spot_checks"])
