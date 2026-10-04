import time
import uuid
from typing import Any

import requests

from gitgrounded.cases.model import Case
from gitgrounded.sources.variant import Variant
from gitgrounded.targets.base import Target, Transcript, check_url, error_transcript


def _part_texts(parts: list[Any]) -> list[str]:
    out = []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        if isinstance(p.get("text"), str):
            out.append(p["text"])
        elif p.get("data") is not None:
            import json

            out.append(json.dumps(p["data"], ensure_ascii=False))
    return out


def extract_a2a_text(result: dict[str, Any]) -> str:
    texts: list[str] = []
    if result.get("kind") == "message" or ("parts" in result and "artifacts" not in result):
        texts += _part_texts(result.get("parts", []))
    for art in result.get("artifacts", []) or []:
        texts += _part_texts(art.get("parts", []))
    if not texts:
        msg = (result.get("status") or {}).get("message") or {}
        texts += _part_texts(msg.get("parts", []))
    if not texts:
        for m in reversed(result.get("history", []) or []):
            if m.get("role") in ("agent", "ROLE_AGENT"):
                texts += _part_texts(m.get("parts", []))
                break
    return "\n".join(t for t in texts if t)


def unwrap_result(result: dict[str, Any]) -> dict[str, Any]:
    if "message" in result and isinstance(result["message"], dict):
        return {**result["message"], "kind": "message"}
    if "task" in result and isinstance(result["task"], dict):
        return result["task"]
    return result


class A2ATarget(Target):
    kind = "a2a"

    def __init__(self, name: str, cfg):
        self.name = name
        self.cfg = cfg
        self.session = requests.Session()
        self.version: str | None = None if cfg.protocol == "auto" else cfg.protocol

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "kind": "a2a", "url": self.cfg.url}

    def _payload(self, version: str, text: str, context_id: str | None) -> tuple[dict[str, Any], dict[str, str]]:
        mid = uuid.uuid4().hex
        headers = dict(self.cfg.headers)
        if version == "1.0":
            message: dict[str, Any] = {"role": "ROLE_USER", "parts": [{"text": text}], "messageId": mid}
            method = "SendMessage"
            headers.setdefault("A2A-Version", "1.0")
        else:
            message = {"role": "user", "parts": [{"kind": "text", "text": text}], "messageId": mid, "kind": "message"}
            method = "message/send"
        if context_id:
            message["contextId"] = context_id
        return {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": {"message": message}}, headers

    def _post(self, url: str, version: str, text: str, context_id: str | None) -> dict[str, Any]:
        payload, headers = self._payload(version, text, context_id)
        resp = self.session.post(url, json=payload, headers=headers, timeout=self.cfg.timeout_s)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400 and not (isinstance(data, dict) and data.get("error")):
            resp.raise_for_status()
        return data

    def _send(self, url: str, text: str, context_id: str | None) -> dict[str, Any]:
        versions = [self.version] if self.version else ["0.3", "1.0"]
        last: dict[str, Any] = {}
        for v in versions:
            data = self._post(url, v, text, context_id)
            err = data.get("error")
            if err and err.get("code") in (-32601, -32600, -32602) and v != versions[-1]:
                last = data
                continue
            if err:
                raise RuntimeError(f"a2a error {err.get('code')}: {err.get('message')}")
            self.version = v
            return unwrap_result(data.get("result") or {})
        err = last.get("error") or {}
        raise RuntimeError(f"a2a error {err.get('code')}: {err.get('message')}")

    def invoke(self, case: Case, variant: Variant, trial: int) -> Transcript:
        url = variant.overlay.get("url", self.cfg.url)
        turns = [m["content"] for m in case.messages() if m["role"] == "user"]
        request = {"url": url, "turns": turns, "headers": dict(self.cfg.headers)}
        start = time.perf_counter()
        context_id = None
        result: dict[str, Any] = {}
        try:
            check_url(url)
            for text in turns:
                result = self._send(url, text, context_id)
                context_id = result.get("contextId") or context_id
        except Exception as e:
            return error_transcript(case, variant, trial, request, f"{type(e).__name__}: {e}")
        text = extract_a2a_text(result)
        return Transcript(
            case_id=case.id,
            variant=variant.name,
            trial=trial,
            request=request,
            raw_output=text,
            output=text,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
