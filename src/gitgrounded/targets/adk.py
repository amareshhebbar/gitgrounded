import time
import uuid
from typing import Any

import requests

from gitgrounded.cases.model import Case
from gitgrounded.sources.variant import Variant
from gitgrounded.targets.base import Target, ToolCall, Transcript, check_url, error_transcript


def _get(d: dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in d:
            return d[n]
    return None


def parse_adk_events(events: list[dict[str, Any]]) -> tuple[str, list[ToolCall]]:
    final = ""
    calls: list[ToolCall] = []
    for ev in events or []:
        if ev.get("author") == "user":
            continue
        content = ev.get("content") or {}
        for part in content.get("parts", []) or []:
            fc = _get(part, "functionCall", "function_call")
            fr = _get(part, "functionResponse", "function_response")
            if fc:
                calls.append(ToolCall(name=fc.get("name", ""), arguments=fc.get("args") or {}))
            elif fr:
                for c in reversed(calls):
                    if c.name == fr.get("name") and c.result is None:
                        c.result = fr.get("response")
                        break
            elif isinstance(part.get("text"), str) and part["text"].strip():
                final = part["text"]
    return final, calls


class AdkTarget(Target):
    kind = "adk"

    def __init__(self, name: str, cfg):
        self.name = name
        self.cfg = cfg
        self.session = requests.Session()

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "kind": "adk", "base_url": self.cfg.base_url, "app_name": self.cfg.app_name}

    def invoke(self, case: Case, variant: Variant, trial: int) -> Transcript:
        base = variant.overlay.get("url", self.cfg.base_url).rstrip("/")
        app = variant.overlay.get("app_name", self.cfg.app_name)
        user = self.cfg.user_id
        sid = f"gg-{uuid.uuid4().hex[:16]}"
        turns = [m["content"] for m in case.messages() if m["role"] == "user"]
        request = {"base_url": base, "app_name": app, "turns": turns}
        start = time.perf_counter()
        events: list[dict[str, Any]] = []
        try:
            check_url(base)
            r = self.session.post(
                f"{base}/apps/{app}/users/{user}/sessions/{sid}",
                json={},
                headers=self.cfg.headers,
                timeout=self.cfg.timeout_s,
            )
            r.raise_for_status()
            for text in turns:
                body = {
                    "appName": app,
                    "userId": user,
                    "sessionId": sid,
                    "newMessage": {"role": "user", "parts": [{"text": text}]},
                }
                r = self.session.post(f"{base}/run", json=body, headers=self.cfg.headers, timeout=self.cfg.timeout_s)
                r.raise_for_status()
                data = r.json()
                events = data if isinstance(data, list) else data.get("events", [])
        except Exception as e:
            return error_transcript(case, variant, trial, request, f"{type(e).__name__}: {e}")
        final, calls = parse_adk_events(events)
        return Transcript(
            case_id=case.id,
            variant=variant.name,
            trial=trial,
            request=request,
            raw_output=final,
            output=final,
            tool_calls=calls,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
