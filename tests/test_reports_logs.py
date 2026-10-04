import io
import json

import numpy as np
import pytest
from rich.console import Console

from gitgrounded.cases.loader import load_cases, write_cases
from gitgrounded.cases.model import Case
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.coverage import logs
from gitgrounded.coverage.extract import Behavior
from gitgrounded.errors import ConfigError
from gitgrounded.providers.embeddings import HashEmbedder
from gitgrounded.report import terminal
from gitgrounded.report.model import RunResult
from gitgrounded.store.cache import Cache
from gitgrounded.store.history import History, safe_label


def _console():
    buf = io.StringIO()
    return Console(file=buf, width=200, force_terminal=False), buf


def _trial(raw, passed=True, error=None):
    return {
        "transcript": {"raw_output": raw, "error": error},
        "assertions": [{"label": "json_valid", "passed": passed, "message": "bad json"}],
    }


def _case(cid, status, score, base=True, error=None):
    return {
        "case": {"id": cid, "input": "q"},
        "status": status,
        "reasons": [f"reason {cid}"],
        "delta": {"score": score},
        "head": {"trials": [_trial(None if error else "head " * 50, passed=status != "FAIL", error=error)]},
        "base": {"trials": [_trial("base out")]} if base else None,
    }


def _result(base=True):
    metric = {
        "head": {"mean": 6.0, "ci_lower": 5.0, "ci_upper": 7.0},
        "base": {"mean": 7.0, "ci_lower": 6.0, "ci_upper": 8.0},
        "delta": {"mean": -1.0, "ci_lower": -2.0, "ci_upper": 0.0, "p_adjusted": 0.04},
    }
    return RunResult(
        run_id="r1",
        created_at="2026-01-01T00:00:00Z",
        tool_version="0",
        project="p",
        suite="s",
        mode="git" if base else "check",
        target={"type": "python"},
        base={"name": "main", "sha": "a" * 40} if base else None,
        head={"name": "feat", "sha": "b" * 40},
        verdict="FAIL",
        counts={"total_cases": 5, "fail_cases": 1},
        metrics={
            "score": metric,
            "empty": {},
            "assertion_pass_rate": {"head": {"rate": 0.8}, "base": {"rate": 1.0}},
        },
        pairwise={"n": 3, "head_wins": 1, "base_wins": 2, "ties": 0, "position_consistency": 1.0},
        cost={"run_usd": 0.0123},
        gate_trace=[{"level": "fail", "expr": "fail_cases > 0", "triggered": True}],
        cases=[
            _case("c1", "FAIL", -3.0, base),
            _case("c2", "BROKEN", -2.0, base, error="boom"),
            _case("c3", "WARN", -0.5, base),
            _case("c4", "UNSTABLE", 0.0, base),
            _case("c5", "IMPROVED", 2.0, base),
            _case("c6", "PASS", 0.0, base),
        ],
    )


def test_render_run_with_base():
    con, buf = _console()
    terminal.render_run(_result(), con)
    out = buf.getvalue()
    for word in ("FAIL", "regressions", "warnings", "improvements", "pairwise", "gates fired", "run cost: $0.0123"):
        assert word in out
    assert "boom" in out


def test_render_run_without_base():
    con, buf = _console()
    terminal.render_run(_result(base=False), con, top=2)
    out = buf.getvalue()
    assert "improvements" not in out and "regressions" in out
    terminal.render_run(_result(), None)


def test_terminal_helpers_and_rank():
    assert terminal._fmt(None) == "-"
    assert terminal._fmt(1.23456, 3) == "1.235"
    assert terminal._fmt(3) == "3"
    assert terminal._ci(None) == "-"
    assert terminal._ci({"mean": None}) == "-"
    assert terminal._short("a  b") == "a b"
    assert terminal._short("x" * 50, 10).endswith("...")
    con, buf = _console()
    rows = [
        {
            "rank": 1,
            "name": "a",
            "verdict": "PASS",
            "mean": 7.0,
            "ci_lower": 6.0,
            "ci_upper": 8.0,
            "head_win_rate": 0.5,
            "assertion_failures": 0,
            "tied_with": ["b"],
        },
        {
            "rank": 2,
            "name": "b",
            "verdict": None,
            "mean": None,
            "ci_lower": None,
            "ci_upper": None,
            "head_win_rate": None,
            "assertion_failures": 1,
            "tied_with": [],
        },
    ]
    terminal.render_rank(rows, con)
    assert "ranking" in buf.getvalue()
    terminal.render_rank(rows)


def test_redact_and_presidio(monkeypatch):
    text = "mail a.b@example.com card 4111 1111 1111 1111 pan ABCDE1234F ip 10.0.0.1 phone +91 98765 43210"
    out = logs.redact(text)
    for tag in ("[email]", "[card]", "[pan]", "[ip]"):
        assert tag in out
    assert "example.com" not in out
    assert logs._presidio("x") is None
    monkeypatch.setenv("GITGROUNDED_PRESIDIO", "1")
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("presidio"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert logs._presidio("x") is None


def test_read_logs_formats(tmp_path):
    jl = tmp_path / "a.jsonl"
    jl.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                "plain string",
                {"prompt": "p1", "output": "o"},
                {"question": "q1"},
                {"input": {"content": "dict content"}},
                {"input": {"other": 1}},
                {"messages": [{"role": "assistant", "content": "x"}, {"role": "user", "content": "last user"}]},
                {"messages": [{"role": "assistant", "content": "x"}]},
                {"nothing": True},
            ]
        )
        + "\n\n"
    )
    rows = logs.read_logs(jl)
    inputs = [r["input"] for r in rows]
    assert inputs[:4] == ["plain string", "p1", "q1", "dict content"]
    assert '{"other": 1}' in inputs and "last user" in inputs
    assert len(rows) == 6
    js = tmp_path / "b.json"
    js.write_text(json.dumps({"items": [{"message": "m1"}, {"message": "m2"}]}))
    assert [r["input"] for r in logs.read_logs(js, limit=1)] == ["m1"]
    js.write_text(json.dumps({"data": ["d1"]}))
    assert logs.read_logs(js)[0]["input"] == "d1"
    js.write_text(json.dumps(["x", "y"]))
    assert len(logs.read_logs(js)) == 2


def test_kmeans_choose_k():
    emb = HashEmbedder(64)
    texts = [
        "refund duplicate charge",
        "refund double charge card",
        "refund charged twice",
        "reset password link",
        "password reset email",
        "forgot password login",
        "shipping late package",
        "package shipping tracking",
    ]
    vecs = emb.embed(texts)
    k = logs.choose_k(vecs, max_k=4)
    assert 2 <= k <= 4
    labels = logs.kmeans(vecs, k)
    assert len(labels) == len(texts)
    assert logs.choose_k(vecs[:4]) == 2
    assert logs.choose_k(vecs[:1]) == 1
    assert logs.kmeans(vecs[:1], 5).tolist() == [0]
    same = np.tile(vecs[:1], (4, 1))
    assert len(logs.kmeans(same, 3)) == 4
    assert logs._silhouette(vecs[:2], np.array([0, 1])) == -1.0


def test_analyze_logs(tmp_path):
    path = tmp_path / "logs.jsonl"
    msgs = [
        "I was charged twice, refund the duplicate charge",
        "duplicate charge refund please",
        "double charge on my card refund",
        "how do I reset my password",
        "password reset not working",
        "forgot my password help",
        "what is the weather on mars",
        "tell me a joke about cats",
    ]
    path.write_text("\n".join(json.dumps({"message": m}) for m in msgs))
    behaviors = [
        Behavior(
            id="b-refund",
            statement="Refund duplicate charges within 30 days",
            kind="rule_must",
            triggers=["duplicate charge", "refund"],
        ),
        Behavior(id="b-implicit", statement="Be polite", kind="rule_must", implicit=True),
        Behavior(id="b-unused", statement="Escalate legal threats to a human", kind="rule_must"),
    ]
    cache = Cache(tmp_path / "cache")
    cfg = ProviderCfg()
    out = logs.analyze_logs(path, behaviors, HashEmbedder(128), cfg, cache, max_clusters=4, match_threshold=0.05)
    assert out["total_messages"] == 8
    assert out["clusters"] and out["cases"]
    assert all(c.origin == "log" for c in out["cases"])
    assert "b-implicit" not in out["unseen_behaviors"]
    again = logs.analyze_logs(path, behaviors, HashEmbedder(128), cfg, cache, max_clusters=4)
    assert [c["label"] for c in again["clusters"]] == [c["label"] for c in out["clusters"]]
    none = logs.analyze_logs(path, [], HashEmbedder(128), cfg, cache, max_clusters=3)
    assert all(c["behavior"] is None for c in none["clusters"])
    assert none["untested_traffic"] == none["clusters"]
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert logs.analyze_logs(empty, behaviors, HashEmbedder(16), cfg, cache)["clusters"] == []


def test_load_cases_variants_and_errors(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"cases": ["one", {"query": "two"}, {"id": "x", "prompt": "three"}]}))
    cases = load_cases(p)
    assert [c.id for c in cases] == ["case-0001", "case-0002", "x"]
    assert cases[1].input == "two"
    out = tmp_path / "sub" / "o.jsonl"
    write_cases(out, cases)
    assert [c.id for c in load_cases(out)] == ["case-0001", "case-0002", "x"]
    with pytest.raises(ConfigError, match="not found"):
        load_cases(tmp_path / "missing.jsonl")
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"input": "a"}\n{nope\n')
    with pytest.raises(ConfigError, match=":2: invalid JSON"):
        load_cases(bad)
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_cases(bad)
    bad.write_text(json.dumps([{"id": "a"}]))
    with pytest.raises(ConfigError, match="case 1 invalid"):
        load_cases(bad)
    bad.write_text(json.dumps([{"id": "a", "input": "x"}, {"id": "a", "input": "y"}]))
    with pytest.raises(ConfigError, match="duplicate"):
        load_cases(bad)


def test_cache(tmp_path, monkeypatch):
    c = Cache(tmp_path / "cache")
    assert c.clear() == 0
    k = c.key("a", 1)
    assert c.get("ns", k) is None
    assert c.set("ns", k, {"v": 1}) == {"v": 1}
    assert c.get("ns", k) == {"v": 1}
    c._path("ns", k).write_text("{broken")
    assert c.get("ns", k) is None
    assert c.clear() == 1
    off = Cache(tmp_path / "off", enabled=False)
    assert off.set("ns", k, 5) == 5 and off.get("ns", k) is None
    monkeypatch.setenv("GITGROUNDED_NO_CACHE", "1")
    assert not Cache(tmp_path / "x").enabled


def test_history(tmp_path):
    assert safe_label("  ") == "default"
    assert safe_label("http://a/b") == "http_a_b"
    h = History(tmp_path / "h")
    assert h.labels() == [] and h.versions("x") == [] and h.latest("x") is None
    assert h.delete("x") == 0 and h.delete_all() == 0
    assert h.save("bot", {"a": 1}) == 1
    assert h.save("bot", {"a": 2}) == 2
    (h.dir_for("bot") / "notes.txt").write_text("x")
    assert h.versions("bot") == [1, 2]
    assert h.load("bot", 2)["version"] == 2
    assert h.delete("bot", 9) == 0
    assert h.delete("bot", 1) == 1
    assert h.labels() == [("bot", 2)]
    assert h.delete("bot") == 1
    h.save("a", {})
    h.save("b", {})
    assert h.delete_all() == 2


def test_cases_roundtrip_messages():
    c = Case(id="m", input=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
    assert c.last_user_message() == "u"
    assert "user: u" in c.input_text()
    assert c.messages()[0]["role"] == "system"
