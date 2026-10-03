import json
import time
from typing import Any

import requests

from gitgrounded.cases.model import Case
from gitgrounded.jsonpath import jsonpath_get
from gitgrounded.sources.variant import Variant
from gitgrounded.targets.base import Target, ToolCall, Transcript, check_url, error_transcript


def render(template: Any, case: Case) -> Any:
    if isinstance(template, str):
        if template == "{{input}}":
            return case.last_user_message() if isinstance(case.input, list) else case.input
        if template == "{{messages}}":
            return case.messages()
        if template == "{{case_id}}":
            return case.id
        text = case.input if isinstance(case.input, str) else case.last_user_message()
        return template.replace("{{input}}", text).replace("{{case_id}}", case.id)
    if isinstance(template, dict):
        return {k: render(v, case) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, case) for v in template]
    return template


class HttpTarget(Target):
    kind = "http"

    def __init__(self, name: str, cfg):
        self.name = name
        self.cfg = cfg
        self.session = requests.Session()

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "kind": "http", "url": self.cfg.url, "method": self.cfg.method}

    def invoke(self, case: Case, variant: Variant, trial: int) -> Transcript:
        url = variant.overlay.get("url", self.cfg.url)
        body = render(self.cfg.body, case)
        headers = {k: v for k, v in self.cfg.headers.items()}
        request = {"url": url, "method": self.cfg.method, "body": body, "headers": headers}
        start = time.perf_counter()
        try:
            check_url(url)
            if self.cfg.method == "GET":
                resp = self.session.get(
                    url, params=body if isinstance(body, dict) else None, headers=headers, timeout=self.cfg.timeout_s
                )
            else:
                resp = self.session.request(
                    self.cfg.method, url, json=body, headers=headers, timeout=self.cfg.timeout_s
                )
            latency = (time.perf_counter() - start) * 1000
            resp.raise_for_status()
        except requests.RequestException as e:
            return error_transcript(case, variant, trial, request, f"{type(e).__name__}: {e}")
        raw = resp.text
        try:
            parsed = resp.json()
        except ValueError:
            parsed = None
        output: Any = parsed if parsed is not None else raw
        if self.cfg.output and parsed is not None:
            output = jsonpath_get(parsed, self.cfg.output, default=None)
        context = []
        if self.cfg.context_path and parsed is not None:
            ctx = jsonpath_get(parsed, self.cfg.context_path, default=[]) or []
            context = [
                c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                for c in (ctx if isinstance(ctx, list) else [ctx])
            ]
        tool_calls = []
        if self.cfg.tool_calls_path and parsed is not None:
            calls = jsonpath_get(parsed, self.cfg.tool_calls_path, default=[]) or []
            tool_calls = [
                ToolCall(name=c.get("name", ""), arguments=c.get("arguments", {}) or {}, result=c.get("result"))
                for c in calls
                if isinstance(c, dict)
            ]
        return Transcript(
            case_id=case.id,
            variant=variant.name,
            trial=trial,
            request=request,
            raw_output=raw,
            output=output,
            tool_calls=tool_calls,
            context=context,
            latency_ms=latency,
        )
