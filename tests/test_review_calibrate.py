import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gitgrounded.cases.model import Case, Expectation
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.coverage import review_server
from gitgrounded.coverage.extract import Behavior
from gitgrounded.coverage.review_server import ReviewState
from gitgrounded.coverage.suite_store import SuiteStore
from gitgrounded.judges.calibrate import calibrate, load_labels
from gitgrounded.project import Project
from gitgrounded.store.cache import Cache


@pytest.fixture
def store(tmp_path):
    project = Project(tmp_path, None, tmp_path / ".gitgrounded")
    s = SuiteStore(project, "auto")
    s.write_json(
        "behavior_map.json",
        {"behaviors": [Behavior(id="b1", statement="Refund duplicate charges", kind="rule_must").model_dump()]},
    )
    s.write_cases(
        [
            Case(id="c1", input="charged twice", behaviors=["b1"], origin="synth"),
            Case(id="c2", input="double charge", behaviors=["b1"], origin="synth"),
            Case(id="c3", input="old one", behaviors=["b1"], origin="synth", reviewed=True),
            Case(id="c4", input="no behavior", origin="synth"),
        ]
    )
    return s


def test_review_state(store):
    state = ReviewState(store)
    listing = state.listing()
    assert [c["id"] for c in listing["cases"]] == ["c1", "c2", "c4"]
    assert "b1" in listing["behaviors"]
    assert len(ReviewState(store, only_unreviewed=False).listing()["cases"]) == 4
    assert state.decide({"id": "zzz", "action": "accept"})["ok"] is False
    assert state.decide({"id": "c1", "action": "explode"})["ok"] is False
    assert state.decide({"id": "c1", "action": "accept"}) == {"ok": True, "remaining": 2}
    assert state.decide({"id": "c2", "action": "reject"})["ok"] is True
    res = state.decide(
        {
            "id": "c4",
            "action": "edit",
            "input": "edited input",
            "expectations": [{"kind": "must_not", "text": "leak"}, {"kind": "weird", "text": "x"}, {"text": ""}],
        }
    )
    assert res == {"ok": True, "remaining": 0}
    cases = {c.id: c for c in store.cases()}
    assert "c2" not in cases and cases["c1"].reviewed
    c4 = cases["c4"]
    assert c4.input == "edited input" and c4.meta["edited"]
    assert [(e.kind, e.text) for e in c4.expectations] == [("must_not", "leak"), ("must", "x")]
    state.decide({"id": "c3", "action": "edit", "expectations": [{"text": "keep"}]})
    c3 = {c.id: c for c in store.cases()}["c3"]
    assert c3.expectations == [Expectation(kind="must", text="keep", behavior_id="b1")]
    log = store.path("review.jsonl").read_text().splitlines()
    assert [json.loads(line)["action"] for line in log] == ["accept", "reject", "edit", "edit"]


def _request(url, data=None, raw=None):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_serve_handler(store, monkeypatch, capsys):
    captured = {}
    opened = []

    class FakeServer:
        def __init__(self, addr, handler):
            captured["handler"] = handler
            captured["addr"] = addr

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            captured["closed"] = True

    class InstantTimer:
        def __init__(self, delay, fn):
            self.fn = fn

        def start(self):
            self.fn()

    monkeypatch.setattr(review_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(review_server.threading, "Timer", InstantTimer)
    monkeypatch.setattr(review_server.webbrowser, "open", lambda url: opened.append(url))
    review_server.serve(store, 8123, open_browser=True)
    assert captured["closed"] and captured["addr"] == ("127.0.0.1", 8123)
    assert opened == ["http://127.0.0.1:8123/"]
    assert "review UI" in capsys.readouterr().out

    server = ThreadingHTTPServer(("127.0.0.1", 0), captured["handler"])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        code, body = _request(base + "/")
        assert code == 200 and b"GitGrounded review" in body
        code, body = _request(base + "/api/cases")
        assert code == 200 and len(json.loads(body)["cases"]) == 3
        assert _request(base + "/nope")[0] == 404
        assert _request(base + "/nope", {"a": 1})[0] == 404
        assert _request(base + "/api/decision", raw=b"{bad")[0] == 400
        code, body = _request(base + "/api/decision", {"id": "c1", "action": "accept"})
        assert code == 200 and json.loads(body)["ok"] is True
    finally:
        server.shutdown()
        server.server_close()


def _labels(tmp_path):
    p = tmp_path / "labels.jsonl"
    rows = [
        {
            "input": "charged twice",
            "output": "Duplicate charges are refunded within 30 days per policy line 1.",
            "expectations": [{"text": "duplicate charges refunded within 30 days"}],
            "score": 9,
            "pass": True,
        },
        {
            "case": {"id": "custom", "input": "refund marketplace"},
            "output": {"answer": "contact support"},
            "context": "policy",
            "score": 3,
            "pass": False,
        },
        {"id": "only-pass", "input": "hello", "output": "hi", "pass": True},
        {"input": "nothing", "output": "x"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    return p


def test_calibrate(tmp_path):
    p = _labels(tmp_path)
    assert len(load_labels(p)) == 4
    out = calibrate(p, "grounded_answer", ProviderCfg(), Cache(tmp_path / "cache"), tmp_path, 6.0)
    assert out["labels"] == 4
    assert out["rubric"] == "grounded_answer"
    assert out["pass_agreement"] is not None
    assert [d["id"] for d in out["details"]] == ["label-0", "custom", "only-pass", "label-3"]
    assert out["details"][3]["human_score"] is None


def test_calibrate_no_pass_labels(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps({"input": "a", "output": "b", "score": 4}) + "\n")
    out = calibrate(p, "grounded_answer", ProviderCfg(), Cache(tmp_path / "c"), tmp_path)
    assert out["pass_agreement"] is None
