import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

import gitgrounded.cli.main as cli
from gitgrounded.cli.main import main


def run_cli(args):
    with pytest.raises(SystemExit) as e:
        main(args)
    return e.value.code


RUN = ["run", "--base", "baseline", "--no-generate"]


def _logs(demo_repo):
    rows = [
        "I was charged twice for my subscription, please refund",
        "double charge on my card yesterday, contact me at a@b.com",
        "duplicate payment showed up on my statement",
        "how do I reset my password",
        "password reset link never arrives",
        "cannot log in, forgot my password",
        "where is my package, shipping is late",
        "my order has not shipped yet",
        "tracking number for my shipment please",
        {"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "refund for marketplace item"}]},
    ]
    path = demo_repo / "data" / "logs.jsonl"
    path.write_text("\n".join(json.dumps(r if isinstance(r, dict) else {"message": r}) for r in rows) + "\n")
    cfg_path = demo_repo / "gitgrounded.yml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["suites"]["auto"]["coverage"]["sources"]["logs"] = "data/logs.jsonl"
    cfg["suites"]["auto"]["coverage"]["budget_cases"] = 20
    cfg["suites"]["auto"]["coverage"]["mutation"]["max_mutants"] = 2
    cfg_path.write_text(yaml.safe_dump(cfg))


def test_version_help_and_interrupt(monkeypatch, capsys):
    assert run_cli(["--version"]) == 0
    assert "gitgrounded" in capsys.readouterr().out
    assert run_cli(["--help"]) == 0

    def boom(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_schema", boom)
    assert run_cli(["schema"]) == 130
    assert cli._exit_code("WARN", "warn") == 1
    assert cli._exit_code("PASS", "warn") == 0
    assert cli._pct(None) == "n/a"


def test_run_outputs_report_bundle_verify(demo_repo, tmp_path, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))
    step = tmp_path / "step.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    out = tmp_path / "out"
    out.mkdir()
    code = run_cli(
        RUN
        + [
            "--head",
            "test/drop-citation-rule",
            "--bundle",
            "--sign",
            "local",
            "--html",
            str(out / "r.html"),
            "--markdown",
            str(out / "r.md"),
            "--junit",
            str(out / "r.xml"),
            "--json-out",
            str(out / "r.json"),
            "--open",
            "--verbose",
        ]
    )
    assert code == 1
    text = capsys.readouterr().out
    assert "regressions" in text and "evidence bundle" in text
    assert opened and step.read_text()
    for name in ("r.html", "r.md", "r.xml", "r.json"):
        assert (out / name).stat().st_size > 0
    monkeypatch.delenv("GITHUB_STEP_SUMMARY")

    assert run_cli(RUN + ["--head", "test/safe-wording-tweak", "--format", "markdown", "--quick"]) == 0
    assert "GitGrounded" in capsys.readouterr().out
    assert run_cli(RUN + ["--head", "test/drop-citation-rule", "--fail-on", "warn", "--format", "json"]) == 1
    capsys.readouterr()

    assert run_cli(["report"]) == 0
    assert run_cli(["report", "--format", "html", "--open"]) == 0
    assert run_cli(["report", "--format", "html", "--out", str(out / "x.html")]) == 0
    assert run_cli(["report", "--format", "markdown", "--out", str(out / "x.md")]) == 0
    assert run_cli(["report", "--format", "junit"]) == 0
    assert "<testsuite" in capsys.readouterr().out
    assert run_cli(["report", "--format", "junit", "--out", str(out / "x.xml")]) == 0
    assert run_cli(["report", "--format", "json"]) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    run_dir = demo_repo / ".gitgrounded" / "runs" / run_id
    assert run_cli(["report", str(run_dir), "--format", "markdown"]) == 0

    bundle = tmp_path / "b.ggb"
    assert run_cli(["bundle", "--out", str(bundle), "--sign", "local"]) == 0
    assert "merkle" in capsys.readouterr().out
    assert run_cli(["report", str(bundle)]) == 2
    assert run_cli(["verify", str(bundle)]) == 0
    assert "VERIFIED" in capsys.readouterr().out
    assert run_cli(["verify", str(bundle), "--verbose"]) == 0
    assert "check" in capsys.readouterr().out
    assert run_cli(["verify", str(bundle), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"].startswith("VERIFIED")
    assert run_cli(["verify", str(bundle), "--public-key", "0000000000000000"]) == 1

    unsigned = tmp_path / "u.ggb"
    assert run_cli(["bundle", "--out", str(unsigned), "--sign", "none"]) == 0
    assert run_cli(["verify", str(unsigned)]) == 0


def test_report_without_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run_cli(["init"]) == 0
    assert run_cli(["init", "--force"]) == 0
    assert run_cli(["report"]) == 2
    assert run_cli(["bundle"]) == 2
    assert run_cli(["cache", "clear"]) == 0


def test_rank_and_misc(demo_repo, capsys):
    cands = ["test/safe-wording-tweak", "test/drop-citation-rule"]
    assert run_cli(["rank", "--base", "baseline", "--no-generate", *cands]) == 0
    assert "ranking" in capsys.readouterr().out
    assert run_cli(["rank", "--base", "baseline", "--no-generate", "--format", "json", "test/drop-citation-rule"]) == 1
    assert run_cli(["check"]) == 2
    assert run_cli(["check", "--url", "http://127.0.0.1:9/x"]) == 2
    assert run_cli(["mcp", "diff"]) == 2
    assert run_cli(["doctor"]) == 0
    assert "offline mode: ON" in capsys.readouterr().out
    assert run_cli(["cache", "clear"]) == 0
    assert "cleared" in capsys.readouterr().out


def test_coverage_commands(demo_repo, tmp_path, monkeypatch, capsys):
    _logs(demo_repo)
    assert run_cli(["suite", "coverage", "--suite", "auto"]) == 2
    assert run_cli(["suite", "review", "--suite", "auto"]) == 2
    assert run_cli(["discover", "--suite", "auto"]) == 0
    assert "behaviors from" in capsys.readouterr().out
    assert run_cli(["discover", "--suite", "auto", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["behaviors"]
    assert run_cli(["synth", "--suite", "auto"]) == 0
    assert "suite v" in capsys.readouterr().out
    assert run_cli(["synth", "--suite", "auto", "--format", "json", "--no-logs"]) == 0
    assert json.loads(capsys.readouterr().out)["cases"] > 0
    assert run_cli(["synth", "--suite", "auto", "--full", "--format", "json"]) == 0
    capsys.readouterr()
    assert run_cli(["mutate", "--suite", "auto", "--max-mutants", "2", "--no-repair"]) == 0
    assert "mutation score" in capsys.readouterr().out
    mut = run_cli(["mutate", "--suite", "auto", "--max-mutants", "2", "--format", "json", "--fail-on", "target"])
    out = json.loads(capsys.readouterr().out)
    assert mut == (0 if out["meets_target"] else 1)

    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))
    assert run_cli(["suite", "coverage", "--suite", "auto", "--open"]) == 0
    assert opened
    assert run_cli(["suite", "coverage", "--suite", "auto", "--html", str(tmp_path / "c.html")]) == 0
    assert (tmp_path / "c.html").exists()
    capsys.readouterr()
    assert run_cli(["suite", "coverage", "--suite", "auto", "--format", "json"]) == 0
    assert "summary" in json.loads(capsys.readouterr().out)
    assert run_cli(["suite", "show", "--suite", "auto"]) == 0

    calls = []
    import gitgrounded.coverage.review_server as rs

    monkeypatch.setattr(rs, "serve", lambda store, port, open_browser, only_unreviewed: calls.append(port))
    assert run_cli(["suite", "review", "--suite", "auto", "--no-browser", "--port", "1"]) == 0
    assert calls == [1]

    assert run_cli(["suite", "import", "--suite", "auto"]) == 2
    src = tmp_path / "in.json"
    src.write_text(json.dumps(["hello", {"message": "refund please"}]))
    dest = tmp_path / "out.jsonl"
    assert run_cli(["suite", "import", "--suite", "auto", "--file", str(src), "--out", str(dest)]) == 0
    assert len(dest.read_text().splitlines()) == 2

    assert run_cli(
        ["run", "--suite", "auto", "--base", "baseline", "--head", "test/drop-citation-rule", "--minimal"]
    ) in (
        0,
        1,
    )
    capsys.readouterr()
    code = run_cli(
        [
            "run",
            "--suite",
            "auto",
            "--base",
            "baseline",
            "--head",
            "test/drop-citation-rule",
            "--quick",
            "--certify",
            "--sign",
            "local",
            "--format",
            "json",
            "--out",
            str(tmp_path / "cert.ggb"),
        ]
    )
    assert code in (0, 1)
    assert (tmp_path / "cert.ggb").exists()
    assert "CERTIFIED" in capsys.readouterr().out


def test_calibrate_cli(demo_repo, tmp_path, capsys):
    labels = tmp_path / "labels.jsonl"
    rows = [
        {
            "input": "charged twice",
            "output": "Duplicate charges are refunded within 30 days per policy line 1.",
            "expectations": [{"text": "duplicate charges refunded within 30 days"}],
            "score": 9,
            "pass": True,
        },
        {
            "input": "refund marketplace item",
            "output": {"answer": "no idea"},
            "expectations": [{"text": "cannot refund third party marketplace purchases"}],
            "score": 2,
            "pass": False,
        },
        {"input": "hello", "output": "hi", "score": 5},
    ]
    labels.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    assert run_cli(["calibrate", "--labels", str(labels)]) == 0
    assert "spearman" in capsys.readouterr().out
    assert run_cli(["calibrate", "--labels", str(labels), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["labels"] == 3
    assert (demo_repo / ".gitgrounded" / "calibration.json").exists()


def test_history_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert run_cli(["init"]) == 0
    assert run_cli(["history"]) == 0
    assert "no stored history" in capsys.readouterr().out
    assert run_cli(["history", "import", str(tmp_path / "missing")]) == 2
    versions = tmp_path / ".versions" / "bot"
    versions.mkdir(parents=True)
    for n in (1, 2):
        (versions / f"v{n}.json").write_text(
            json.dumps({"answers": [{"input": "q1", "raw": "a", "parsed": {"x": n}}, {"input": "q2", "raw": "b"}]})
        )
    (versions / "vX.json").write_text(json.dumps({"answers": []}))
    assert run_cli(["history", "import"]) == 0
    assert "imported 3" in capsys.readouterr().out
    assert run_cli(["history", "list"]) == 0
    assert "bot" in capsys.readouterr().out
    assert run_cli(["history", "bot", "--rank"]) == 0
    assert "did not regress" in capsys.readouterr().out
    assert run_cli(["history", "nope"]) == 2
    assert run_cli(["history", "delete"]) == 2
    assert run_cli(["history", "delete", "bot", "--version", "3"]) == 0
    assert "deleted 1" in capsys.readouterr().out
    assert run_cli(["history", "delete", "bot"]) == 0
    assert "deleted 2" in capsys.readouterr().out
    assert run_cli(["history", "import"]) == 0
    assert run_cli(["history", "delete", "--all"]) == 0
    assert "deleted 1 label" in capsys.readouterr().out


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


@pytest.fixture
def http_stub():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    STATE["good"] = True
    yield f"http://127.0.0.1:{server.server_port}/chat"
    server.shutdown()
    server.server_close()


def test_check_cli(tmp_path, monkeypatch, capsys, http_stub):
    monkeypatch.chdir(tmp_path)
    cfg = {
        "targets": {"bot": {"type": "http", "url": http_stub, "output": "$.reply.text"}},
        "suites": {"live": {"target": "bot", "generate": {"enabled": False}}},
    }
    (tmp_path / "gitgrounded.yml").write_text(yaml.safe_dump(cfg))
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        "\n".join(
            json.dumps({"input": q, "expectations": [{"text": "duplicate charges refunded within 30 days"}]})
            for q in ("charged twice", "double charge")
        )
    )
    assert run_cli(["check", "--cases", str(cases), "--format", "json"]) == 0
    assert "stored baseline" in capsys.readouterr().out
    STATE["good"] = False
    assert run_cli(["check", "bot", "--cases", str(cases), "--format", "json"]) == 1
    assert run_cli(["check", "other", "--cases", str(cases)]) == 2
    STATE["good"] = True
    code = run_cli(
        [
            "check",
            "--url",
            http_stub,
            "--output",
            "$.reply.text",
            "--cases",
            str(cases),
            "--label",
            "adhoc",
            "--format",
            "json",
        ]
    )
    assert code == 0
    assert run_cli(["history", "list"]) == 0
    assert "adhoc" in capsys.readouterr().out


def test_mcp_diff_formats(tmp_path, capsys):
    tool = {"name": "t", "description": "Get the weather", "inputSchema": {"type": "object", "properties": {}}}
    old = tmp_path / "a.json"
    new = tmp_path / "b.json"
    old.write_text(json.dumps({"tools": [tool]}))
    changed = dict(
        tool,
        description="Delete every file on disk",
        inputSchema={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    new.write_text(json.dumps({"tools": [changed]}))
    args = ["mcp", "diff", "--old-file", str(old), "--new-file", str(new)]
    assert run_cli(args + ["--format", "json", "--fail-on", "never"]) == 0
    assert "summary" in json.loads(capsys.readouterr().out)
    assert run_cli(args + ["--fail-on", "risky"]) in (0, 1)
    assert "semver" in capsys.readouterr().out


def test_compare_and_benchmark_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    (tmp_path / "v1.txt").write_text("You are a bot for ACME. Always cite the policy line.")
    (tmp_path / "v2.txt").write_text("You are a bot. Keep it short.")
    (tmp_path / "policy.md").write_text("# Policy\n1. Refunds up to 100 USD within 30 days.\n")
    (tmp_path / "gg_cli_bots.py").write_text(
        "def good(message):\n    return 'Refunds up to 100 USD within 30 days (policy line 1).'\n\n"
        "def bad(message):\n    return 'No idea.'\n"
    )
    cfg = {
        "targets": {
            "good": {"type": "python", "entry": "gg_cli_bots:good"},
            "bad": {"type": "python", "entry": "gg_cli_bots:bad"},
        }
    }
    (tmp_path / "gitgrounded.yml").write_text(yaml.safe_dump(cfg))
    try:
        cmp = ["compare", "--prompt", "v1.txt", "--prompt", "v2.txt", "--model", "openai", "--context", "policy.md"]
        assert run_cli(cmp + ["--quick", "--open"]) == 0
        assert "leaderboard" in capsys.readouterr().out
        assert run_cli(cmp + ["--quick", "--format", "json"]) == 0
        out = capsys.readouterr().out
        assert '"leaderboard"' in out
        assert run_cli(["compare", "--prompt", "v1.txt", "--model", "openai", "--quick"]) == 0
        bench = ["benchmark", "--spec", "v1.txt", "--context", "policy.md", "--quick"]
        assert run_cli(bench + ["--format", "json"]) == 0
        assert '"leaderboard"' in capsys.readouterr().out
        code = run_cli(bench + ["--certify", "--sign", "local", "--out", str(tmp_path / "b.ggb")])
        assert code in (0, 1)
        assert (tmp_path / "b.ggb").exists()
    finally:
        sys.modules.pop("gg_cli_bots", None)


def test_mcp_diff_tools_file_target(tmp_path, monkeypatch, capsys):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    monkeypatch.chdir(tmp_path)
    tool = {"name": "weather", "description": "Get the weather", "inputSchema": {"type": "object", "properties": {}}}
    (tmp_path / "tools.json").write_text(json.dumps({"tools": [tool]}))
    cfg = {"targets": {"srv": {"type": "mcp", "tools_file": "tools.json"}}}
    (tmp_path / "gitgrounded.yml").write_text(yaml.safe_dump(cfg))
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    (tmp_path / "tools.json").write_text(json.dumps({"tools": []}))
    assert run_cli(["mcp", "diff", "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["summary"]["breaking"] == 1
    assert run_cli(["mcp", "diff", "--target", "srv", "--fail-on", "never"]) == 0


def test_doctor_ping_and_flags(demo_repo, tmp_path, monkeypatch, capsys):
    assert run_cli(["doctor", "--ping"]) == 0
    assert "ok " in capsys.readouterr().out
    bundle = tmp_path / "x.ggb"
    args = RUN + ["--head", "test/safe-wording-tweak", "--budget-usd", "5", "--concurrency", "2", "--format", "json"]
    assert run_cli(args + ["--bundle", str(bundle), "--sign", "none"]) == 0
    assert bundle.exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert run_cli(["doctor"]) == 0
    assert run_cli(["certifier", "pubkey", "--home", str(tmp_path / "cert")]) == 0
    assert "key_id" in capsys.readouterr().out
