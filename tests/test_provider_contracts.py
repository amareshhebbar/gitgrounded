import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gitgrounded.config.schema import ProviderCfg
from gitgrounded.errors import ProviderError
from gitgrounded.providers import base
from gitgrounded.providers.base import build_provider, reset_provider_cache
from gitgrounded.providers.llm import complete_json
from gitgrounded.providers.usage import USAGE


class FakeApi:
    def __init__(self):
        self.requests = []
        self.responses = []
        self.default = (200, {})
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                outer.requests.append(
                    {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
                )
                status, payload, *extra = outer.responses.pop(0) if outer.responses else outer.default
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (extra[0] if extra else {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("GITGROUNDED_OFFLINE", "0")
    monkeypatch.delenv("GITGROUNDED_MODE", raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)
    reset_provider_cache()
    fake = FakeApi()
    yield fake
    fake.close()
    reset_provider_cache()


OPENAI_OK = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "test-model",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
}

ANTHROPIC_OK = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-test",
    "content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "claude"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 9, "output_tokens": 4},
}


def _cfg(api, provider, **kw):
    base_url = api.url + ("/v1" if provider in ("openai", "groq", "deepseek", "custom") else "")
    return ProviderCfg(provider=provider, model="m", base_url=base_url, max_retries=kw.pop("max_retries", 1), **kw)


def test_openai_compatible_request_and_response(api, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    api.default = (200, OPENAI_OK)
    p = build_provider(_cfg(api, "openai", temperature=0.3, max_tokens=77, seed=5))
    out = p.complete("be brief", [{"role": "user", "content": "hi"}], json_mode=True)
    req = api.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["authorization"] == "Bearer sk-test"
    body = req["body"]
    assert body["model"] == "m"
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    assert body["messages"][1] == {"role": "user", "content": "hi"}
    assert body["temperature"] == 0.3 and body["max_tokens"] == 77 and body["seed"] == 5
    assert body["response_format"] == {"type": "json_object"}
    assert out.text == "hello there"
    assert (out.input_tokens, out.output_tokens) == (11, 5)
    assert out.provider == "openai"
    assert USAGE.snapshot()["models"]["test-model"]["calls"] == 1


def test_openai_compatible_without_system_or_json(api, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    api.default = (200, OPENAI_OK)
    p = build_provider(_cfg(api, "groq"))
    p.complete("", [{"role": "user", "content": "hi"}])
    body = api.requests[0]["body"]
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert "response_format" not in body and "seed" not in body


def test_openai_compatible_empty_content(api, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    empty = json.loads(json.dumps(OPENAI_OK))
    empty["choices"][0]["message"]["content"] = None
    api.default = (200, empty)
    out = build_provider(_cfg(api, "openai")).complete("", [{"role": "user", "content": "x"}])
    assert out.text == ""


def test_custom_provider_needs_no_key(api, monkeypatch):
    for name in ("GITGROUNDED_CUSTOM_API_KEY", "CUSTOM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    api.default = (200, OPENAI_OK)
    out = build_provider(_cfg(api, "custom")).complete("", [{"role": "user", "content": "x"}])
    assert out.text == "hello there"


def test_missing_key_message_mentions_offline(api, monkeypatch):
    for name in ("OPENAI_API_KEY", "GITGROUNDED_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderError, match="GITGROUNDED_OFFLINE=1"):
        build_provider(_cfg(api, "openai"))
    for name in ("ANTHROPIC_API_KEY", "GITGROUNDED_ANTHROPIC_API_KEY", "GITGROUNDED_CLAUDE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        build_provider(_cfg(api, "anthropic"))


def test_anthropic_request_and_response(api, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    api.default = (200, ANTHROPIC_OK)
    p = build_provider(_cfg(api, "anthropic", temperature=0.2, max_tokens=50))
    out = p.complete("system text", [{"role": "user", "content": "question"}], json_mode=True)
    req = api.requests[0]
    assert req["path"] == "/v1/messages"
    assert req["headers"]["x-api-key"] == "sk-ant-test"
    assert "anthropic-version" in req["headers"]
    body = req["body"]
    assert body["system"] == "system text"
    assert body["max_tokens"] == 50
    if p.temperature_supported:
        assert body["temperature"] == 0.2
    else:
        assert "temperature" not in body
    assert body["messages"][-1]["content"].startswith("question")
    assert "valid JSON object only" in body["messages"][-1]["content"]
    assert out.text == "hello claude"
    assert (out.input_tokens, out.output_tokens) == (9, 4)
    assert out.model == "claude-test"


def test_anthropic_without_system_leaves_field_out(api, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    api.default = (200, ANTHROPIC_OK)
    build_provider(_cfg(api, "anthropic")).complete("", [{"role": "user", "content": "q"}])
    assert "system" not in api.requests[0]["body"]


def test_ollama_request_and_response(api):
    api.default = (
        200,
        {"model": "qwen", "created_at": "t", "message": {"content": "ok"}, "prompt_eval_count": 3, "eval_count": 2},
    )
    p = build_provider(_cfg(api, "ollama", seed=9))
    out = p.complete("sys", [{"role": "user", "content": "q"}], json_mode=True)
    req = api.requests[0]
    assert req["path"] == "/api/chat"
    body = req["body"]
    assert body["stream"] is False and body["format"] == "json"
    assert body["options"]["seed"] == 9
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert out.text == "ok" and (out.input_tokens, out.output_tokens) == (3, 2)


def test_retries_then_succeeds_on_429(api, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    api.responses = [(429, {"error": {"message": "slow down"}}, {"retry-after": "0"})]
    api.default = (200, OPENAI_OK)
    p = build_provider(_cfg(api, "openai", max_retries=3))
    assert p.complete("", [{"role": "user", "content": "x"}]).text == "hello there"
    assert len(api.requests) == 2


def test_persistent_failure_raises_provider_error(api, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    api.default = (500, {"type": "error", "error": {"type": "api_error", "message": "boom"}})
    p = build_provider(_cfg(api, "anthropic", max_retries=2))
    with pytest.raises(ProviderError, match="failed after 2 attempts"):
        p.complete("", [{"role": "user", "content": "x"}])
    assert len(api.requests) == 2


def test_ollama_http_error_raises(api):
    api.default = (500, {"error": "model not found"})
    p = build_provider(_cfg(api, "ollama", max_retries=1))
    with pytest.raises(ProviderError):
        p.complete("", [{"role": "user", "content": "x"}])


def test_budget_exceeded_is_not_retried(api, monkeypatch):
    from gitgrounded.errors import BudgetExceeded

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    api.default = (200, OPENAI_OK)
    USAGE.configure({"test-model": [1000000.0, 1000000.0]}, 0.0001)
    p = build_provider(_cfg(api, "openai", max_retries=3))
    with pytest.raises(BudgetExceeded):
        p.complete("", [{"role": "user", "content": "x"}])
    assert len(api.requests) == 1
    USAGE.configure({}, None)


def test_unknown_model_with_budget_refuses(api, monkeypatch):
    from gitgrounded.errors import BudgetExceeded

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("GITGROUNDED_ALLOW_UNKNOWN_COST", raising=False)
    api.default = (200, OPENAI_OK)
    USAGE.configure({}, 5.0)
    p = build_provider(_cfg(api, "openai"))
    with pytest.raises(BudgetExceeded, match="no price known"):
        p.complete("", [{"role": "user", "content": "x"}])
    USAGE.reset()
    monkeypatch.setenv("GITGROUNDED_ALLOW_UNKNOWN_COST", "1")
    assert p.complete("", [{"role": "user", "content": "x"}]).text == "hello there"
    USAGE.configure({}, None)


def test_price_overrides_from_environment(monkeypatch):
    monkeypatch.setenv("GITGROUNDED_PRICES", json.dumps({"my-model": [1.0, 2.0], "bad": "x"}))
    USAGE.configure({}, None)
    USAGE.record("my-model-v2", 1_000_000, 1_000_000)
    assert abs(USAGE.cost() - 3.0) < 1e-9
    assert USAGE.unpriced_models() == []
    USAGE.record("mystery", 10, 10)
    assert USAGE.unpriced_models() == ["mystery"]
    assert USAGE.snapshot()["unpriced_models"] == ["mystery"]


def test_complete_json_repairs_fenced_output(api, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fenced = json.loads(json.dumps(OPENAI_OK))
    fenced["choices"][0]["message"]["content"] = '```json\n{"a": 1}\n```'
    api.default = (200, fenced)
    data, _ = complete_json(build_provider(_cfg(api, "openai")), "s", "u", "task")
    assert data == {"a": 1}


def test_retry_after_parsing():
    class Resp:
        headers = {"retry-after": "7"}

    class Err(Exception):
        response = Resp()

    assert base._retry_after(Err()) == 7.0
    assert base._retry_after(Exception("x")) is None


def test_offline_flag_overrides_real_provider(monkeypatch):
    monkeypatch.setenv("GITGROUNDED_OFFLINE", "1")
    reset_provider_cache()
    assert type(build_provider(ProviderCfg(provider="anthropic", model="x"))).__name__ == "MockProvider"


def test_anthropic_temperature_detection():
    from gitgrounded.providers.anthropic import _accepts

    def with_temperature(*, temperature=None):
        return None

    def without_temperature(*, max_tokens=1):
        return None

    def with_kwargs(**kwargs):
        return None

    assert _accepts(with_temperature, "temperature")
    assert not _accepts(without_temperature, "temperature")
    assert _accepts(with_kwargs, "temperature")
