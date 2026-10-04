import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from gitgrounded.cases.model import Case
from gitgrounded.config.loader import parse_config
from gitgrounded.engine import Engine
from gitgrounded.project import Project
from gitgrounded.providers import env


def test_env_specs(monkeypatch):
    monkeypatch.setenv("GITGROUNDED_DEEPSEEK_MODEL", "deepseek-reasoner")
    monkeypatch.setenv("GITGROUNDED_OLLAMA_TEMPERATURE", "0.3")
    assert env.parse_spec("claude") == {"provider": "anthropic", "model": "claude-sonnet-4-6"}
    assert env.parse_spec("deepseek")["model"] == "deepseek-reasoner"
    assert env.parse_spec("ollama:llama3.1:8b") == {"provider": "ollama", "model": "llama3.1:8b", "temperature": 0.3}
    with pytest.raises(ValueError):
        env.parse_spec("nope:x")


def test_keys_fallback(monkeypatch):
    monkeypatch.delenv("GITGROUNDED_CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "std")
    assert env.api_key("claude") == "std"
    monkeypatch.setenv("GITGROUNDED_ANTHROPIC_API_KEY", "gg")
    assert env.api_key("anthropic") == "gg"


def test_role_layer_and_priority(monkeypatch):
    monkeypatch.setenv("GITGROUNDED_JUDGE", "openai:gpt-4.1")
    monkeypatch.setenv("GITGROUNDED_JUDGE_TEMPERATURE", "0")
    monkeypatch.setenv("GITGROUNDED_PANEL", "groq,deepseek")
    cfg = parse_config({})
    assert cfg.providers.judge.provider == "openai" and cfg.providers.judge.model == "gpt-4.1"
    assert [p.provider for p in cfg.providers.panel] == ["groq", "deepseek"]
    cfg = parse_config({"providers": {"judge": {"provider": "claude", "model": "x"}}})
    assert cfg.providers.judge.model == "x"


def _write(tmp_path):
    (tmp_path / "v1.txt").write_text(
        "You are a bot for ACME. Always cite the policy line. Never promise refunds above 100 USD."
    )
    (tmp_path / "v2.txt").write_text("You are a bot for ACME. Keep it short.")
    (tmp_path / "policy.md").write_text(
        "# Policy\n1. Refunds up to 100 USD within 30 days.\n2. Late shipping over 7 days gets a credit.\n"
    )


def test_compare_grid_and_certificate(tmp_path):
    from gitgrounded.compare import run_compare
    from gitgrounded.coverage.suite_store import SuiteStore
    from gitgrounded.evidence.certify import certify
    from gitgrounded.evidence.verify import verify_bundle

    _write(tmp_path)
    engine = Engine(Project(tmp_path, None, tmp_path / ".gitgrounded"), parse_config({}))
    res = run_compare(engine, ["v1.txt", "v2.txt"], ["openai", "claude"], context=["policy.md"], budget=16)
    assert len(res.candidates) == 4 and len(res.results) == 3
    assert {r["candidate"] for r in res.leaderboard} == {c.name for c in res.candidates}
    v2 = [r for r in res.leaderboard if r["prompt"] == "v2"]
    assert all(r["delta"] < 0 for r in v2)
    again = run_compare(engine, ["v2.txt", "v1.txt"], ["openai", "claude"], context=["policy.md"], budget=16)
    assert again.suite == res.suite
    info = certify(engine, res.suite, res.cases, res.results, res.leaderboard, tmp_path / "c.ggb", "local")
    assert info["traps"]["passed"]
    assert info["reasons"] == ["offline mock mode: real models were not used"]
    assert verify_bundle(tmp_path / "c.ggb").status == "VERIFIED_SELF_SIGNED"
    if info["pdf"]:
        import zipfile

        pdf = Path(info["pdf"]).read_bytes()
        assert pdf.startswith(b"%PDF") and zipfile.ZipFile(tmp_path / "c.ggb").read("certificate.pdf") == pdf
        assert info["qr"].startswith(f"ggcert:{info['certificate']['id']};certified=no;sha256=")
    store = SuiteStore(engine.project, res.suite)
    p = store.path("current.jsonl")
    p.write_text(p.read_text().replace('"input": "', '"input": "X', 1))
    info = certify(engine, res.suite, store.cases(), res.results, res.leaderboard, tmp_path / "d.ggb", "local")
    assert any("sealed" in r for r in info["reasons"])
    engine.close()


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        if self.path.startswith("/apps/"):
            out = {"id": "s"}
        elif self.path == "/run":
            text = body["newMessage"]["parts"][0]["text"]
            out = [
                {"author": "agent", "content": {"parts": [{"functionCall": {"name": "lookup", "args": {"q": text}}}]}},
                {
                    "author": "agent",
                    "content": {"parts": [{"functionResponse": {"name": "lookup", "response": {"ok": 1}}}]},
                },
                {"author": "agent", "content": {"parts": [{"text": f"adk says {text}"}]}},
            ]
        else:
            text = body["params"]["message"]["parts"][0]["text"]
            out = {
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "kind": "task",
                    "contextId": "c1",
                    "artifacts": [{"parts": [{"kind": "text", "text": f"a2a says {text}"}]}],
                },
            }
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_a2a_and_adk_targets(tmp_path):
    from gitgrounded.sources.variant import Variant
    from gitgrounded.targets.base import build_target

    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    cfg = parse_config(
        {
            "targets": {
                "a": {"type": "a2a", "url": f"{base}/"},
                "k": {"type": "adk", "base_url": base, "app_name": "demo"},
            }
        }
    )
    v = Variant("live", tmp_path, {}, "h")
    case = Case(id="c", input="hello")
    a = build_target("a", cfg.targets["a"], None).invoke(case, v, 0)
    assert a.output == "a2a says hello" and not a.error
    k = build_target("k", cfg.targets["k"], None).invoke(case, v, 0)
    assert k.output == "adk says hello"
    assert k.tool_calls[0].name == "lookup" and k.tool_calls[0].result == {"ok": 1}
    server.shutdown()
