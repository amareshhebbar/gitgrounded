import os
import json
import time
import requests

MOCK_TRIAGE_RESPONSE = {
    "category": "billing",
    "priority": "medium",
    "answer": "Mock answer for testing.",
    "policy_line": "1. Refunds are issued in full for duplicate charges within 30 days of the original transaction.",
}

MOCK_GENERATE_RESPONSE = {
    "cases": [
        {"id": "mock-1", "input": "Mock generated case one, a duplicate charge scenario."},
        {"id": "mock-2", "input": "Mock generated case two, a refund window edge case."},
    ]
}

MOCK_JUDGE_RESPONSE = {
    "groundedness": 8,
    "format_correctness": 8,
    "rule_following": 8,
    "meaning_drift": 1,
    "reason": "mock judge response, deterministic for testing",
}


def _call_mock(system, user, json_mode):
    lowered = system.lower()
    if "test case generator" in lowered:
        return json.dumps(MOCK_GENERATE_RESPONSE)
    if "strict evaluator" in lowered:
        return json.dumps(MOCK_JUDGE_RESPONSE)
    return json.dumps(MOCK_TRIAGE_RESPONSE)


def _call_ollama(base_url, model, system, user, json_mode):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": False,
        "keep_alive": "30m",
    }
    if json_mode:
        payload["format"] = "json"
    resp = requests.post(f"{base_url}/api/chat", json=payload, timeout=180)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _call_groq(base_url, model, system, user, json_mode):
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=base_url)
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **kwargs,
    )
    return resp.choices[0].message.content


def _call_claude(model, system, user, json_mode):
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = user
    if json_mode:
        prompt += "\n\nRespond with valid JSON only. No markdown fences, no preamble."
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def call(provider, model, system, user, json_mode=False, providers_config=None):
    providers_config = providers_config or {}

    if provider == "ollama":
        base_url = providers_config.get("ollama", {}).get("base_url", "http://localhost:11434")
        return _call_ollama(base_url, model, system, user, json_mode)

    if provider == "groq":
        base_url = providers_config.get("groq", {}).get("base_url", "https://api.groq.com/openai/v1")
        return _call_groq(base_url, model, system, user, json_mode)

    if provider == "claude":
        return _call_claude(model, system, user, json_mode)

    if provider == "mock":
        return _call_mock(system, user, json_mode)

    raise ValueError(f"unknown provider: {provider}")


class LLMCallFailed(Exception):
    pass


def call_with_retry(provider, model, system, user, json_mode=False, providers_config=None, max_attempts=3, backoff_seconds=2):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return call(provider, model, system, user, json_mode=json_mode, providers_config=providers_config)
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                time.sleep(backoff_seconds * attempt)
    raise LLMCallFailed(f"{provider}/{model} failed after {max_attempts} attempts: {last_error}") from last_error


def call_json_with_retry(provider, model, system, user, providers_config=None, max_attempts=3, backoff_seconds=2):
    last_error = None
    retry_user = user
    for attempt in range(1, max_attempts + 1):
        try:
            raw = call_with_retry(
                provider, model, system, retry_user,
                json_mode=True, providers_config=providers_config,
                max_attempts=1,
            )
            return json.loads(raw), raw
        except (json.JSONDecodeError, LLMCallFailed) as e:
            last_error = e
            retry_user = user + "\n\nYour previous response was not valid JSON. Respond with valid JSON only."
            if attempt < max_attempts:
                time.sleep(backoff_seconds * attempt)
    raise LLMCallFailed(f"{provider}/{model} never returned valid JSON after {max_attempts} attempts: {last_error}")