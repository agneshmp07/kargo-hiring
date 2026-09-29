"""Acceptance test 3: a 0.5/1 code with a null (or empty) quote is forced to 0."""
from conftest import FakeClassifier, good_classification, write_cv_docx
from shortlister import llm, pipeline, store


def test_null_evidence_forced_to_zero():
    obj = llm.empty_result("KG-0001", "x")
    obj["layer_a"]["P1"] = {"code": 1, "evidence": None}
    obj["layer_a"]["P3"] = {"code": 0.5, "evidence": "   "}
    obj["layer_b"]["PM"]["shipped_with_adoption"] = {"code": 1, "evidence": None}
    obj["layer_a"]["P2"] = {"code": 1, "evidence": "Built a tracker the other branches adopted"}
    flags = llm.enforce_evidence(obj, "Built a tracker the other branches adopted")

    assert obj["layer_a"]["P1"]["code"] == 0
    assert obj["layer_a"]["P3"]["code"] == 0
    assert obj["layer_b"]["PM"]["shipped_with_adoption"]["code"] == 0
    assert obj["layer_a"]["P2"]["code"] == 1  # has a real quote, untouched
    flagged = {f["var"] for f in flags if f["flag"] == "no evidence found"}
    assert flagged == {"P1", "P3", "PM.shipped_with_adoption"}


def test_long_quote_trimmed_and_unverified_quote_flagged():
    obj = llm.empty_result("KG-0001", "x")
    obj["layer_a"]["P4"] = {"code": 1, "evidence": " ".join(["word"] * 40)}
    obj["layer_a"]["P5"] = {"code": 0.5, "evidence": "a sentence that is not in the CV"}
    flags = llm.enforce_evidence(obj, "word " * 40)
    assert len(obj["layer_a"]["P4"]["evidence"].split()) <= 26
    assert any(f["var"] == "P5" and f["flag"] == "quote not found verbatim" for f in flags)


def test_forced_zero_flows_into_score(env):
    def no_quote_for_p1(payload):
        obj = good_classification(payload)
        obj["layer_a"]["P1"]["evidence"] = None
        return obj

    write_cv_docx(env / "applications" / "cv_a_pm.docx")
    pipeline.run_batch(classifier=FakeClassifier(no_quote_for_p1), log=lambda *_: None)
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["llm_json"]["layer_a"]["P1"]["code"] == 0
    # Layer A without P1: 10.9 + 21.7 + 21.7 + 13.0 = 67.3
    assert c["results_json"]["PM"]["layer_a"] == 67.3


def test_model_cannot_supply_a_score_or_band():
    obj = llm.empty_result("KG-0001", "x")
    obj.update({"final": 99, "band": "Strong", "rationale": "Great pedigree from IIT. Ran port ops."})
    notes = llm.scrub_policy(obj)
    assert "final" not in obj and "band" not in obj
    assert "IIT" not in obj["rationale"] and "port ops" in obj["rationale"]
    assert notes
