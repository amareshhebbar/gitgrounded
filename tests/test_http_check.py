import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from gitgrounded.cases.model import Case, Expectation
from gitgrounded.config.loader import parse_config
from gitgrounded.engine import Engine, RunOptions
from gitgrounded.project import Project

STATE = {"good": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        text = f"Duplicate charges are refunded within 30 days. ({body['message']})" if STATE["good"] else "No idea."
        out = json.dumps({"reply": {"text": text}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def test_check_history(tmp_path):
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/chat"
    cfg = parse_config(
        {
            "targets": {
                "bot": {"type": "http", "url": url, "output": "$.reply.text", "headers": {"Authorization": "Bearer x"}}
            },
            "suites": {"live": {"target": "bot", "generate": {"enabled": False}}},
        }
    )
    project = Project(tmp_path, None, tmp_path / ".gitgrounded")
    engine = Engine(project, cfg)
    cases = [
        Case(id=f"c{i}", input=q, expectations=[Expectation(text="duplicate charges refunded within 30 days")])
        for i, q in enumerate(["charged twice", "double charge"])
    ]
    first = engine.run_check("live", "bot", RunOptions(), cases=cases)
    assert first.base is None and first.verdict == "PASS"
    STATE["good"] = False
    second = engine.run_check("live", "bot", RunOptions(), cases=cases)
    assert second.base["version"] == 1
    assert second.verdict == "FAIL"
    assert engine.history.latest("bot") == 2
    server.shutdown()
    engine.close()
