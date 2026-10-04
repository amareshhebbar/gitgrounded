import hmac
import ipaddress
import json
import queue
import re
import socket
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from gitgrounded import __version__
from gitgrounded.errors import ConfigError

REMOTE_TYPES = {"http", "a2a", "adk", "mcp"}
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
MAX_BODY = 2 * 1024 * 1024


def _target_urls(target: dict[str, Any]) -> list[str]:
    t = target.get("type")
    if t == "adk":
        return [target.get("base_url") or ""]
    return [target.get("url") or ""]


def _private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def validate_target(target: Any, allow_private: bool = False) -> dict[str, Any]:
    if not isinstance(target, dict):
        raise ConfigError("target must be an object")
    if target.get("type") not in REMOTE_TYPES:
        raise ConfigError(f"target type must be one of {sorted(REMOTE_TYPES)}; the service only tests remote agents")
    if target.get("type") == "mcp" and target.get("transport") != "http":
        raise ConfigError("mcp targets must use transport: http")
    if "${" in json.dumps(target):
        raise ConfigError("environment references are not allowed in submitted targets")
    for key in ("watch", "command", "env", "tools_file"):
        if target.get(key):
            raise ConfigError(f"field {key} is not allowed for remote certification")
    for url in _target_urls(target):
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ConfigError(f"invalid target url: {url!r}")
        if not allow_private and (u.scheme != "https" or _private(u.hostname)):
            raise ConfigError("target url must be https and resolve to a public address")
    return target


class CertifierService:
    def __init__(
        self,
        home: Path,
        tokens: set[str],
        key_path: Path | None = None,
        name: str = "gitgrounded-certifier",
        allow_private: bool = False,
        max_cases: int = 200,
        public_url: str | None = None,
    ):
        from gitgrounded.evidence.sign import LocalSigner

        if not tokens:
            raise ConfigError("set GITGROUNDED_CERTIFIER_TOKENS to at least one token")
        self.home = Path(home)
        self.jobs_dir = self.home / "jobs"
        self.certs_dir = self.home / "certificates"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.certs_dir.mkdir(parents=True, exist_ok=True)
        self.tokens = set(tokens)
        self.name = name
        self.allow_private = allow_private
        self.max_cases = max_cases
        self.public_url = public_url
        self.signer = LocalSigner(key_path or self.home / "certifier_ed25519.pem", scope="independent", issuer=name)
        self.pub = self.signer.public_key()
        self.queue: queue.Queue[str | None] = queue.Queue()
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def authorized(self, header: str | None) -> bool:
        if not header or not header.startswith("Bearer "):
            return False
        given = header[7:].strip()
        return any(hmac.compare_digest(given, t) for t in self.tokens)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "job.json"

    def job(self, job_id: str) -> dict[str, Any] | None:
        if not ID_RE.match(job_id):
            return None
        p = self._job_path(job_id)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _save(self, job: dict[str, Any]) -> None:
        p = self._job_path(job["id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
        tmp.replace(p)

    def submit(self, body: dict[str, Any]) -> dict[str, Any]:
        target = validate_target(body.get("target"), self.allow_private)
        spec = body.get("spec") or ""
        context = body.get("context") or []
        if not isinstance(spec, str) or not isinstance(context, list) or not all(isinstance(c, str) for c in context):
            raise ConfigError("spec must be a string and context a list of strings")
        if not spec.strip() and not context:
            raise ConfigError("send spec and/or context so questions can be generated")
        budget = int(body.get("budget_cases") or 40)
        if not 1 <= budget <= self.max_cases:
            raise ConfigError(f"budget_cases must be between 1 and {self.max_cases}")
        name = str(body.get("name") or "candidate")[:80]
        job = {
            "id": time.strftime("%Y%m%d%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:10],
            "status": "queued",
            "name": name,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "budget_cases": budget,
            "target_type": target["type"],
        }
        d = self.jobs_dir / job["id"] / "input"
        d.mkdir(parents=True, exist_ok=True)
        (d / "target.json").write_text(json.dumps(target), encoding="utf-8")
        (d / "spec.txt").write_text(spec, encoding="utf-8")
        for i, c in enumerate(context):
            (d / f"context_{i}.md").write_text(c, encoding="utf-8")
        self._save(job)
        self.queue.put(job["id"])
        return job

    def _work(self) -> None:
        while True:
            job_id = self.queue.get()
            if job_id is None:
                return
            job = self.job(job_id)
            if job is None:
                continue
            job["status"] = "running"
            self._save(job)
            try:
                job.update(self.run_job(job))
                job["status"] = "done"
            except Exception as e:
                job["status"] = "failed"
                job["error"] = f"{type(e).__name__}: {e}"
                (self.jobs_dir / job_id / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            job["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._save(job)

    def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        from gitgrounded.compare import run_benchmark
        from gitgrounded.config.loader import parse_config
        from gitgrounded.engine import Engine
        from gitgrounded.evidence.certify import certify
        from gitgrounded.project import Project

        root = self.jobs_dir / job["id"]
        inp = root / "input"
        target = json.loads((inp / "target.json").read_text(encoding="utf-8"))
        work = root / "project"
        work.mkdir(exist_ok=True)
        (work / "spec.txt").write_text((inp / "spec.txt").read_text(encoding="utf-8"), encoding="utf-8")
        ctx = []
        for p in sorted(inp.glob("context_*.md")):
            (work / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            ctx.append(p.name)
        cfg = parse_config({"version": 1, "project": {"name": job["name"]}, "targets": {"candidate": target}})
        project = Project(work, None, work / ".gitgrounded")
        engine = Engine(project, cfg)
        try:
            specs = ["spec.txt"] if (work / "spec.txt").read_text(encoding="utf-8").strip() else []
            with self.lock:
                res = run_benchmark(engine, ["candidate"], specs, ctx, budget=job["budget_cases"], regenerate=True)
            out = self.certs_dir / f"{job['id']}.ggb"
            issuer = {
                "name": self.name,
                "scope": "independent",
                "key_id": self.pub["key_id"],
                "url": self.public_url,
                "service_version": __version__,
            }
            info = certify(
                engine,
                res.suite,
                res.cases,
                res.results,
                res.leaderboard,
                out,
                kind="independent_benchmark",
                signer=self.signer,
                issuer=issuer,
            )
        finally:
            engine.close()
        return {
            "certificate_id": job["id"],
            "certified": info["certified"],
            "reasons": info["reasons"],
            "traps": info["traps"],
            "key_id": self.pub["key_id"],
            "has_pdf": bool(info.get("pdf")),
        }

    def certificate_file(self, cert_id: str, ext: str) -> Path | None:
        if not ID_RE.match(cert_id) or ext not in ("ggb", "pdf", "html"):
            return None
        p = self.certs_dir / f"{cert_id}.{ext}"
        return p if p.exists() else None

    def close(self) -> None:
        self.queue.put(None)


def make_handler(svc: CertifierService):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"gitgrounded-certifier/{__version__}"

        def log_message(self, fmt, *args):
            return

        def _send(self, code: int, body: Any, ctype: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body, indent=2).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path.rstrip("/")
            if path == "/health":
                return self._send(200, {"ok": True, "name": svc.name, "version": __version__})
            if path == "/pubkey":
                return self._send(200, {"name": svc.name, **svc.pub})
            m = re.match(r"^/certificates/([^/]+?)(?:\.(ggb|pdf|html))?$", path)
            if m:
                ext = m.group(2) or "ggb"
                f = svc.certificate_file(m.group(1), ext)
                if f is None:
                    return self._send(404, {"error": "not found"})
                ctype = {"ggb": "application/zip", "pdf": "application/pdf", "html": "text/html; charset=utf-8"}[ext]
                return self._send(200, f.read_bytes(), ctype)
            m = re.match(r"^/jobs/([^/]+)$", path)
            if m:
                if not svc.authorized(self.headers.get("Authorization")):
                    return self._send(401, {"error": "unauthorized"})
                job = svc.job(m.group(1))
                return self._send(200, job) if job else self._send(404, {"error": "not found"})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path.rstrip("/") != "/jobs":
                return self._send(404, {"error": "not found"})
            if not svc.authorized(self.headers.get("Authorization")):
                return self._send(401, {"error": "unauthorized"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._send(413, {"error": "body missing or too large"})
            try:
                body = json.loads(self.rfile.read(length))
                job = svc.submit(body if isinstance(body, dict) else {})
            except (ValueError, ConfigError) as e:
                return self._send(400, {"error": str(e)})
            return self._send(202, job)

    return Handler


def serve(svc: CertifierService, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(svc))
