import json
from dataclasses import asdict, dataclass, field
from typing import Any

from gitgrounded.cases.model import Case
from gitgrounded.sources.variant import Variant


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass
class Transcript:
    case_id: str
    variant: str
    trial: int
    request: dict[str, Any]
    raw_output: str
    output: Any
    tool_calls: list[ToolCall] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    provider_response_id: str | None = None
    error: str | None = None
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tool_calls"] = [asdict(t) for t in self.tool_calls]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Transcript":
        d = dict(d)
        d["tool_calls"] = [ToolCall(**t) for t in d.get("tool_calls", [])]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def text(self) -> str:
        if isinstance(self.output, str):
            return self.output
        try:
            return json.dumps(self.output, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(self.output)

    def parsed_json(self) -> Any:
        if isinstance(self.output, (dict, list)):
            return self.output
        try:
            return json.loads(self.raw_output)
        except (TypeError, ValueError):
            return None


def normalize_result(result: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"output": None, "raw": "", "tool_calls": [], "context": [], "usage": {}, "model": None}
    if isinstance(result, str):
        out["output"] = result
        out["raw"] = result
        return out
    if isinstance(result, dict):
        if "parsed" in result or "valid_json" in result:
            out["output"] = result.get("parsed") if result.get("parsed") is not None else result.get("raw")
            out["raw"] = result.get("raw") if isinstance(result.get("raw"), str) else json.dumps(out["output"])
        elif "output" in result:
            out["output"] = result["output"]
            out["raw"] = (
                result["output"]
                if isinstance(result["output"], str)
                else json.dumps(result["output"], ensure_ascii=False)
            )
        else:
            out["output"] = result
            out["raw"] = json.dumps(result, ensure_ascii=False, default=str)
        calls = result.get("tool_calls") or []
        out["tool_calls"] = [
            {
                "name": c.get("name", ""),
                "arguments": c.get("arguments", c.get("args", {})) or {},
                "result": c.get("result"),
            }
            for c in calls
            if isinstance(c, dict)
        ]
        ctx = result.get("context") or []
        out["context"] = [c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) for c in ctx]
        usage = result.get("usage") or {}
        out["usage"] = {
            "input_tokens": int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0),
            "output_tokens": int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0),
        }
        out["model"] = result.get("model")
        return out
    out["output"] = result
    out["raw"] = json.dumps(result, ensure_ascii=False, default=str)
    return out


def transcript_from_result(
    case: Case, variant: Variant, trial: int, request: dict[str, Any], result: Any, latency_ms: float
) -> Transcript:
    n = normalize_result(result)
    return Transcript(
        case_id=case.id,
        variant=variant.name,
        trial=trial,
        request=request,
        raw_output=n["raw"] if isinstance(n["raw"], str) else str(n["raw"]),
        output=n["output"],
        tool_calls=[ToolCall(**c) for c in n["tool_calls"]],
        context=n["context"],
        latency_ms=latency_ms,
        input_tokens=n["usage"].get("input_tokens", 0),
        output_tokens=n["usage"].get("output_tokens", 0),
        model=n["model"],
    )


def error_transcript(case: Case, variant: Variant, trial: int, request: dict[str, Any], error: str) -> Transcript:
    return Transcript(
        case_id=case.id,
        variant=variant.name,
        trial=trial,
        request=request,
        raw_output="",
        output=None,
        error=error[-4000:],
    )


def check_url(url: str) -> None:
    import os
    from urllib.parse import urlparse

    allow = [h.strip().lower() for h in os.environ.get("GITGROUNDED_HTTP_ALLOW", "").split(",") if h.strip()]
    if not allow:
        return
    host = (urlparse(url).hostname or "").lower()
    if not any(host == a or host.endswith("." + a) for a in allow):
        raise PermissionError(f"host {host} is not in GITGROUNDED_HTTP_ALLOW")


class Target:
    name: str = "target"
    kind: str = "base"

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind}

    def invoke(self, case: Case, variant: Variant, trial: int) -> Transcript:
        raise NotImplementedError

    async def ainvoke(self, case: Case, variant: Variant, trial: int) -> Transcript:
        import asyncio

        return await asyncio.to_thread(self.invoke, case, variant, trial)

    def close(self) -> None:
        return None

    def supports_mutation(self) -> bool:
        return False


def build_target(name: str, cfg, project, providers_cfg=None) -> Target:
    kind = cfg.type
    if kind in ("python", "agent", "framework"):
        from gitgrounded.targets.python_callable import PythonTarget

        return PythonTarget(name, cfg)
    if kind == "http":
        from gitgrounded.targets.http_json import HttpTarget

        return HttpTarget(name, cfg)
    if kind == "openai_chat":
        from gitgrounded.targets.openai_chat import OpenAIChatTarget

        return OpenAIChatTarget(name, cfg)
    if kind == "mcp":
        from gitgrounded.targets.mcp_server import McpTarget

        return McpTarget(name, cfg, project)
    if kind == "a2a":
        from gitgrounded.targets.a2a import A2ATarget

        return A2ATarget(name, cfg)
    if kind == "adk":
        from gitgrounded.targets.adk import AdkTarget

        return AdkTarget(name, cfg)
    raise ValueError(f"unknown target type {kind}")
