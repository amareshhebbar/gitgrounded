import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

from gitgrounded.certifier.service import CertifierService, serve, validate_target
from gitgrounded.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "real_agents"


def test_validate_target():
    ok = {"type": "a2a", "url": "http://127.0.0.1:1/"}
    assert validate_target(ok, allow_private=True) == ok
    for bad in (
        {"type": "python", "entry": "x:y"},
        {"type": "mcp", "transport": "stdio", "command": ["x"]},
        {"type": "http", "url": "https://${SECRET}.example.com"},
        {"type": "http", "url": "ftp://x"},
        {"type": "a2a", "url": "https://x.example", "watch": ["a"]},
    ):
        with pytest.raises(ConfigError):
            validate_target(bad, allow_private=True)
    with pytest.raises(ConfigError):
        validate_target(ok)
    with pytest.raises(ConfigError):
        validate_target({"type": "a2a", "url": "https://localhost/"})


def test_certifier_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    pytest.importorskip("a2a.server.routes")
    from gitgrounded.certifier.client import CertifierClient
    from gitgrounded.cli.main import main
    from gitgrounded.evidence.verify import verify_bundle
    from tests.test_real_agents import _port, _serve

    monkeypatch.syspath_prepend(str(EX))
    import a2a_server

    port = _port()
    agent_url = f"http://127.0.0.1:{port}/"
    agent = _serve(a2a_server.build_app(agent_url), port)
    svc = CertifierService(tmp_path / "svc", {"tok"}, allow_private=True, name="test-certifier")
    httpd = serve(svc, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        c = CertifierClient(url, "bad")
        with pytest.raises(Exception, match="401"):
            c.submit({"type": "a2a", "url": agent_url}, "x", [], 5, "n")
        c = CertifierClient(url, "tok")
        with pytest.raises(Exception, match="400"):
            c.submit({"type": "python", "entry": "a:b"}, "x", [], 5, "n")
        pub = c.pubkey()
        assert pub["name"] == "test-certifier"

        work = tmp_path / "proj"
        shutil.copytree(EX, work, ignore=shutil.ignore_patterns("__pycache__", ".gitgrounded"))
        monkeypatch.chdir(work)
        monkeypatch.setenv("A2A_URL", agent_url)
        monkeypatch.setenv("GITGROUNDED_CERTIFIER_TOKEN", "tok")
        out = tmp_path / "remote.ggb"
        args = ["certify-remote", "--service", url, "--target", "a2a_agent", "--spec", "spec.txt"]
        args += ["--context", "policy.md", "--budget-cases", "10", "--out", str(out)]
        with pytest.raises(SystemExit) as e:
            main(args)
        assert e.value.code == 1
        res = verify_bundle(out, public_key=pub["key_id"])
        assert res.status == "VERIFIED_INDEPENDENT"
        assert verify_bundle(out).status == "VERIFIED_SELF_SIGNED"
        assert verify_bundle(out, public_key="AAAA").status == "SIGNATURE_INVALID"
        import zipfile

        cert = json.loads(zipfile.ZipFile(out).read("certificate.json"))
        assert cert["issuer"]["scope"] == "independent" and cert["issuer"]["key_id"] == pub["key_id"]
        assert cert["kind"] == "independent_benchmark"
        assert any("offline" in r for r in cert["reasons"])
        cid = out.stem
        jobs = list((tmp_path / "svc" / "jobs").iterdir())
        assert len(jobs) == 1 and json.loads((jobs[0] / "job.json").read_text())["status"] == "done"
        import requests

        assert requests.get(f"{url}/certificates/{jobs[0].name}").status_code == 200
        assert requests.get(f"{url}/certificates/../x").status_code == 404
        assert requests.get(f"{url}/jobs/{jobs[0].name}").status_code == 401
        assert cid
    finally:
        httpd.shutdown()
        svc.close()
        agent.should_exit = True
        for m in ("support", "a2a_server"):
            sys.modules.pop(m, None)
