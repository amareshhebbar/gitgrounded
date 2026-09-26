import json
import pytest

from gitgrounded.llm import call, call_json_with_retry, LLMCallFailed


def test_mock_triage_response():
    raw = call("mock", "mock", "You are a customer support triage assistant.", "hi", json_mode=True)
    parsed = json.loads(raw)
    assert parsed["category"] == "billing"
    assert "policy_line" in parsed


def test_mock_generate_response():
    raw = call("mock", "mock", "You are a test case generator for regressions.", "diff text", json_mode=True)
    parsed = json.loads(raw)
    assert "cases" in parsed
    assert len(parsed["cases"]) == 2


def test_mock_judge_response():
    raw = call("mock", "mock", "You are a strict evaluator for support triage.", "eval this", json_mode=True)
    parsed = json.loads(raw)
    assert parsed["groundedness"] == 8


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        call("not-a-real-provider", "x", "sys", "usr")


def test_call_json_with_retry_returns_parsed_and_raw():
    parsed, raw = call_json_with_retry("mock", "mock", "You are a strict evaluator.", "eval this")
    assert parsed["groundedness"] == 8
    assert isinstance(raw, str)


def test_call_json_with_retry_fails_after_max_attempts():
    with pytest.raises(LLMCallFailed):
        call_json_with_retry("not-a-real-provider", "x", "sys", "usr", max_attempts=2, backoff_seconds=0)