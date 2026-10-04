import shutil
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "real_agents"


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app, port: int):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    return server


@pytest.fixture
def ex_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EX))
    yield EX
    for m in ("support", "langgraph_app", "strands_app", "a2a_server", "adk_server"):
        sys.modules.pop(m, None)


def _variant():
    from gitgrounded.sources.variant import Variant

    return Variant(name="head", root=Path("."), files={}, content_hash="x")


def test_real_langgraph_and_strands(ex_path):
    pytest.importorskip("langgraph")
    pytest.importorskip("strands")
    import langgraph_app
    import strands_app

    from gitgrounded.targets import frameworks as fw

    r = fw.invoke(langgraph_app.build_graph(), "my package is late", "langgraph")
    assert r["tool_calls"][0]["name"] == "lookup_policy" and "credit" in r["output"]
    assert fw.invoke(langgraph_app.build_graph(), "tell a joke", "langgraph")["tool_calls"] == []
    agent = strands_app.build_agent()
    r = fw.invoke(agent, "I want a refund", "strands")
    assert r["tool_calls"][0]["arguments"] == {"topic": "refund"} and r["output"].endswith("purchase.")
    r = fw.invoke(agent, "parcel is late", "strands")
    assert len(r["tool_calls"]) == 1 and r["usage"]["input_tokens"] > 0


@pytest.mark.parametrize("compat", [True, False])
def test_real_a2a_server(ex_path, compat):
    pytest.importorskip("a2a.server.routes")
    import a2a_server

    from gitgrounded.cases.model import Case
    from gitgrounded.config.schema import A2ATarget as Cfg
    from gitgrounded.targets.a2a import A2ATarget

    port = _port()
    url = f"http://127.0.0.1:{port}/"
    server = _serve(a2a_server.build_app(url, v03_compat=compat), port)
    try:
        t = A2ATarget("a2a", Cfg(type="a2a", url=url))
        tr = t.invoke(Case(id="c", input="refund please"), _variant(), 0)
        assert tr.error is None and "100 USD" in tr.output
        assert t.version == ("0.3" if compat else "1.0")
        tr = A2ATarget("a2a", Cfg(type="a2a", url=url, protocol="1.0")).invoke(Case(id="c", input="hi"), _variant(), 0)
        assert tr.output == "I can only help with refunds and shipping."
    finally:
        server.should_exit = True


def test_real_adk_server(ex_path):
    pytest.importorskip("google.adk")
    import adk_server

    from gitgrounded.cases.model import Case
    from gitgrounded.config.schema import AdkTarget as Cfg
    from gitgrounded.targets.adk import AdkTarget

    port = _port()
    server = _serve(adk_server.build_app(), port)
    try:
        t = AdkTarget("adk", Cfg(type="adk", base_url=f"http://127.0.0.1:{port}", app_name="support_adk"))
        tr = t.invoke(Case(id="c", input="my package is late"), _variant(), 0)
        assert tr.error is None and "credit" in tr.output
        assert tr.tool_calls[0].name == "lookup_policy"
    finally:
        server.should_exit = True


def test_benchmark_real_frameworks(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("strands")
    pytest.importorskip("a2a.server.routes")
    from gitgrounded.cli.main import main

    work = tmp_path / "real"
    shutil.copytree(EX, work, ignore=shutil.ignore_patterns("__pycache__", ".gitgrounded"))
    monkeypatch.chdir(work)
    monkeypatch.syspath_prepend(str(work))
    import a2a_server

    port = _port()
    url = f"http://127.0.0.1:{port}/"
    monkeypatch.setenv("A2A_URL", url)
    server = _serve(a2a_server.build_app(url), port)
    try:
        args = ["benchmark", "--spec", "spec.txt", "--context", "policy.md", "--budget-cases", "8", "--format", "json"]
        for t in ("langgraph_agent", "strands_agent", "a2a_agent"):
            args += ["--target", t]
        try:
            main(args)
        except SystemExit as e:
            assert e.code == 0
    finally:
        server.should_exit = True
        for m in ("support", "a2a_server"):
            sys.modules.pop(m, None)
    runs = list((work / ".gitgrounded" / "runs").glob("*/result.json"))
    assert len(runs) == 2
    assert "lookup_policy" in "".join(p.read_text() for p in runs)
