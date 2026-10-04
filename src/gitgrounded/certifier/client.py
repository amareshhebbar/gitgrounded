import json
import time
from pathlib import Path
from typing import Any

import requests

from gitgrounded.errors import GitGroundedError


class CertifierClient:
    def __init__(self, url: str, token: str | None, timeout_s: float = 60.0):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.timeout = timeout_s

    def _check(self, resp: requests.Response) -> requests.Response:
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", resp.text)
            except ValueError:
                msg = resp.text
            raise GitGroundedError(f"certifier returned {resp.status_code}: {msg}")
        return resp

    def pubkey(self) -> dict[str, Any]:
        return self._check(requests.get(f"{self.url}/pubkey", timeout=self.timeout)).json()

    def submit(self, target: dict[str, Any], spec: str, context: list[str], budget_cases: int, name: str) -> dict:
        body = {"target": target, "spec": spec, "context": context, "budget_cases": budget_cases, "name": name}
        r = requests.post(
            f"{self.url}/jobs",
            data=json.dumps(body),
            headers={**self.headers, "Content-Type": "application/json"},
            timeout=self.timeout,
        )
        return self._check(r).json()

    def job(self, job_id: str) -> dict[str, Any]:
        return self._check(requests.get(f"{self.url}/jobs/{job_id}", headers=self.headers, timeout=self.timeout)).json()

    def wait(self, job_id: str, timeout_s: float = 3600.0, poll_s: float = 2.0, log=None) -> dict[str, Any]:
        end = time.monotonic() + timeout_s
        last = None
        while time.monotonic() < end:
            job = self.job(job_id)
            if job["status"] != last and log:
                log(job["status"])
            last = job["status"]
            if job["status"] in ("done", "failed"):
                return job
            time.sleep(poll_s)
        raise GitGroundedError(f"certification job {job_id} did not finish in {timeout_s:.0f}s")

    def download(self, cert_id: str, out: Path, ext: str = "ggb") -> Path:
        r = self._check(requests.get(f"{self.url}/certificates/{cert_id}.{ext}", timeout=self.timeout))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.content)
        return out
