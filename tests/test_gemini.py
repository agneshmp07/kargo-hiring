"""Gemini as the classifier: request shape, parsing, retries, cost, and the free-tier guard."""
import json

import pytest

from conftest import IDENTITY, good_classification, write_cv_docx
from shortlister import config, gemini_client, llm, pipeline, store


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeGemini:
    """Answers like the Interactions API, with the classification for the CV it was sent."""

    def __init__(self, fail_first=0, bad_json_first=0, shape="steps"):
        self.calls, self.fail_first, self.bad_json_first, self.shape = [], fail_first, bad_json_first, shape

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if len(self.calls) <= self.fail_first:
            return Resp(503, {"error": {"message": "overloaded"}})
        payload = {"system": [{"text": json["system_instruction"]}], "messages": [{"content": json["input"]}]}
        text = "{not json" if len(self.calls) <= self.fail_first + self.bad_json_first else \
            __import__("json").dumps(good_classification(payload))
        usage = {"total_input_tokens": 8000, "total_output_tokens": 900, "total_thought_tokens": 100,
                 "total_cached_tokens": 0}
        if self.shape == "output_text":
            return Resp(200, {"status": "completed", "output_text": text, "usage": usage})
        return Resp(200, {"status": "completed", "usage": usage,
                          "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]})


@pytest.fixture
def gem(env, monkeypatch):
    monkeypatch.setenv("KARGO_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("KARGO_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-not-real")
    monkeypatch.setenv("GEMINI_PAID_TIER", "true")
    monkeypatch.setattr(gemini_client.time, "sleep", lambda *_: None)
    return env


def _run(env, monkeypatch, fake):
    import requests

    monkeypatch.setattr(requests, "post", fake.post)
    write_cv_docx(env / "applications" / "cv_a_pm.docx")
    return pipeline.run_batch(log=lambda *_: None)


def test_provider_and_defaults(gem):
    assert config.llm_provider() == "gemini" and config.model() == "gemini-3.8-flash" and config.api_ready()


def test_request_shape_and_redaction(gem, monkeypatch):
    fake = FakeGemini()
    s = _run(gem, monkeypatch, fake)
    assert s["new"] == 1
    c = fake.calls[0]
    assert c["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert c["headers"]["x-goog-api-key"] == "test-gemini-key-not-real" and "User-Agent" in c["headers"]
    body = c["json"]
    assert body["model"] == "gemini-3.8-flash" and body["generation_config"]["temperature"] == 0
    assert body["store"] is False
    assert body["response_format"]["mime_type"] == "application/json"
    assert body["response_format"]["schema"]["properties"]["layer_a"]
    assert llm.ANCHORS in body["system_instruction"]  # anchors verbatim
    blob = json.dumps(body).lower()
    for v in (IDENTITY["name"].lower(), IDENTITY["email"], "iit bombay", "narsee"):
        assert v not in blob  # the same redaction as the Claude path


def test_scores_and_cost(gem, monkeypatch):
    _run(gem, monkeypatch, FakeGemini(shape="output_text"))
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["results_json"]["PM"]["band"] == "Strong"
    # 8000 in @ $0.75/M + (900 + 100 thinking) out @ $3.75/M = $0.00975
    assert c["usage_json"]["cost_usd"] == pytest.approx(0.00975)
    assert c["usage_json"]["model"] == "gemini-3.8-flash"


def test_overload_is_retried_and_bad_json_retried_once(gem, monkeypatch):
    fake = FakeGemini(fail_first=1, bad_json_first=1)
    _run(gem, monkeypatch, fake)
    with store.connect() as conn:
        c = store.get_candidate(conn, "KG-0001")
    assert c["confidence"] != "low" and len(fake.calls) == 3


def test_real_cvs_never_go_to_the_free_tier(gem, monkeypatch):
    monkeypatch.setenv("GEMINI_PAID_TIER", "false")
    fake = FakeGemini()
    with pytest.raises(gemini_client.GeminiError, match="GEMINI_PAID_TIER"):
        _run(gem, monkeypatch, fake)
    assert fake.calls == []  # nothing was sent


def test_demo_may_use_the_free_tier(gem, monkeypatch):
    monkeypatch.setenv("GEMINI_PAID_TIER", "false")
    monkeypatch.setenv("KARGO_DEMO", "1")
    fake = FakeGemini()
    _run(gem, monkeypatch, fake)
    assert len(fake.calls) == 1


def test_claude_stays_the_default(env, monkeypatch):
    monkeypatch.delenv("KARGO_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("KARGO_MODEL", raising=False)
    assert config.llm_provider() == "anthropic" and config.model() == "claude-sonnet-5"
