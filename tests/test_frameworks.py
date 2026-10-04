import shutil
import sys
from pathlib import Path

from gitgrounded.targets import frameworks as fw

ROOT = Path(__file__).resolve().parents[1]


class LangGraphLike:
    def invoke(self, payload, config=None):
        text = payload["messages"][-1]["content"]
        return {
            "messages": [
                {"type": "human", "content": text},
                {"type": "ai", "content": "", "tool_calls": [{"name": "search", "args": {"q": text}, "id": "1"}]},
                {"type": "tool", "content": "found", "tool_call_id": "1"},
                {
                    "type": "ai",
                    "content": f"answer to {text}",
                    "usage_metadata": {"input_tokens": 5, "output_tokens": 3},
                },
            ]
        }


class StrandsLike:
    def __init__(self):
        self.messages = []

    def __call__(self, prompt):
        self.messages += [
            {"role": "assistant", "content": [{"toolUse": {"toolUseId": "a", "name": "calc", "input": {"x": 1}}}]},
            {"role": "user", "content": [{"toolResult": {"toolUseId": "a", "content": [{"text": "2"}]}}]},
        ]
        return f"strands: {prompt}"


class CrewLike:
    def kickoff(self, inputs):
        return type("R", (), {"raw": f"crew: {inputs['input']}", "token_usage": None})()


class DspyLike:
    def __call__(self, question):
        return type("P", (), {"_store": {"reasoning": "r", "answer": f"dspy: {question}"}})()


class AsyncRunner:
    async def run(self, task):
        return {"output": f"async: {task}"}


def test_runners():
    r = fw.invoke(LangGraphLike(), "hi", "langgraph")
    assert r["output"] == "answer to hi"
    assert r["tool_calls"] == [{"name": "search", "arguments": {"q": "hi"}, "result": "found"}]
    assert r["usage"]["input_tokens"] == 5
    r = fw.invoke(StrandsLike(), [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}], "strands")
    assert r["output"] == "strands: b" and r["tool_calls"][0]["name"] == "calc" and r["tool_calls"][0]["result"] == "2"
    assert fw.invoke(CrewLike(), "x", "crewai")["output"] == "crew: x"
    assert fw.invoke(DspyLike(), "q", "dspy")["output"] == "dspy: q"
    assert fw.invoke(AsyncRunner(), "t", "generic")["output"] == "async: t"
    assert fw.invoke(lambda s: s[::-1], "abc", "auto")["output"] == "cba"


def test_benchmark_cli(tmp_path, monkeypatch):
    from gitgrounded.cli.main import main

    work = tmp_path / "fw"
    shutil.copytree(ROOT / "examples" / "frameworks", work)
    monkeypatch.chdir(work)
    monkeypatch.syspath_prepend(str(work))
    try:
        main(["benchmark", "--spec", "spec.txt", "--context", "policy.md", "--budget-cases", "12", "--format", "json"])
    except SystemExit as e:
        assert e.code == 0
    runs = list((work / ".gitgrounded" / "runs").glob("*/result.json"))
    assert len(runs) == 2
    text = "".join(p.read_text() for p in runs)
    assert "lookup_policy" in text
    sys.modules.pop("agents_app", None)
