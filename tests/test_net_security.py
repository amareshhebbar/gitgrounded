import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from gitgrounded import net
from gitgrounded.certifier.service import CertifierService, serve, validate_target
from gitgrounded.errors import ConfigError


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "192.168.0.5",
        "172.16.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "100.64.0.1",
        "0.0.0.0",
        "not an ip",
    ],
)
def test_blocked_addresses(address):
    assert net.is_blocked_ip(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses_allowed(address):
    assert not net.is_blocked_ip(address)


class _Redirector(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


@pytest.fixture
def local_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Redirector)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_strict_session_refuses_loopback(local_server):
    s = net.StrictSession()
    with pytest.raises(requests.exceptions.ConnectionError, match="non public address"):
        s.get(local_server + "/")


def test_strict_session_refuses_redirects(local_server, monkeypatch):
    monkeypatch.setattr(net, "is_blocked_ip", lambda address: False)
    s = net.StrictSession()
    assert s.get(local_server + "/").text == "ok"
    with pytest.raises(net.RedirectBlockedError):
        s.get(local_server + "/redirect")


def test_new_session_follows_strict_flag():
    net.set_strict(False)
    assert not isinstance(net.new_session(), net.StrictSession)
    net.set_strict(True)
    assert isinstance(net.new_session(), net.StrictSession)


def test_validate_target_rejects_private_hosts():
    for url in (
        "https://127.0.0.1/",
        "https://localhost/",
        "https://169.254.169.254/",
        "https://[::1]/",
        "http://example.com/",
    ):
        with pytest.raises(ConfigError):
            validate_target({"type": "http", "url": url})


def _service(tmp_path, **kw):
    pytest.importorskip("cryptography")
    svc = CertifierService(tmp_path / "svc", {"tok"}, allow_private=True, **kw)
    httpd = serve(svc, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return svc, httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _post(url, token, payload=None, raw=None, length=None):
    data = raw if raw is not None else json.dumps(payload).encode()
    req = urllib.request.Request(url + "/jobs", data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if length is not None:
        req.add_header("Content-Length", str(length))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_certifier_rejects_oversized_and_missing_bodies(tmp_path):
    svc, httpd, url = _service(tmp_path)
    try:
        assert _post(url, "tok", raw=b"x" * (2 * 1024 * 1024 + 10)) == 413
        assert _post(url, "tok", raw=b"") == 413
        assert _post(url, "wrong", payload={}) == 401
        assert _post(url, "tok", payload={"target": {"type": "python"}}) == 400
    finally:
        httpd.shutdown()
        svc.close()


def test_certifier_rate_limit(tmp_path):
    svc, httpd, url = _service(tmp_path, max_jobs_per_hour=3)
    try:
        codes = [_post(url, "tok", payload={"target": {"type": "python"}}) for _ in range(5)]
        assert codes[:3] == [400, 400, 400]
        assert codes[3:] == [429, 429]
    finally:
        httpd.shutdown()
        svc.close()


def test_rate_limit_window_expires(tmp_path):
    pytest.importorskip("cryptography")
    svc = CertifierService(tmp_path / "svc", {"tok"}, allow_private=True, max_jobs_per_hour=2)
    try:
        assert svc.allow_submission("a", now=1000.0)
        assert svc.allow_submission("a", now=1001.0)
        assert not svc.allow_submission("a", now=1002.0)
        assert svc.allow_submission("b", now=1002.0)
        assert svc.allow_submission("a", now=1000.0 + 3601)
    finally:
        svc.close()


def test_certifier_enables_strict_network_unless_private_allowed(tmp_path):
    pytest.importorskip("cryptography")
    svc = CertifierService(tmp_path / "a", {"t"}, allow_private=False)
    assert net.is_strict()
    svc.close()
    svc2 = CertifierService(tmp_path / "b", {"t"}, allow_private=True)
    assert not net.is_strict()
    svc2.close()
