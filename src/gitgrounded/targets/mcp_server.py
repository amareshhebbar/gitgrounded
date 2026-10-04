import json
import time
from typing import Any

from gitgrounded.cases.model import Case
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.mcp.introspect import McpClient, load_tools_file
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.sources.variant import Variant
from gitgrounded.targets.base import Target, ToolCall, Transcript, error_transcript

SELECT_SYSTEM = """You are an AI agent connected to an MCP server. Given the user's task and the list of available tools with their JSON input schemas, choose the single best tool to call and the exact arguments. If no tool fits, return tool null.
Return JSON: {"tool": "<name or null>", "arguments": {...}}"""


class McpTarget(Target):
    kind = "mcp"

    def __init__(self, name: str, cfg, project):
        self.name = name
        self.cfg = cfg
        self.project = project
        self._tools: dict[str, list[dict[str, Any]]] = {}

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "mcp",
            "transport": self.cfg.transport,
            "command": self.cfg.command,
            "url": self.cfg.url,
        }

    def supports_mutation(self) -> bool:
        return True

    def client(self, variant: Variant) -> McpClient:
        url = variant.overlay.get("url", self.cfg.url)
        return McpClient(self.cfg.transport, self.cfg.command, url, variant.root, self.cfg.env, self.cfg.timeout_s)

    def tools(self, variant: Variant) -> list[dict[str, Any]]:
        if variant.content_hash in self._tools:
            return self._tools[variant.content_hash]
        if self.cfg.tools_file:
            if self.cfg.tools_file in variant.files:
                data = json.loads(variant.files[self.cfg.tools_file])
                tools = data.get("tools", data) if isinstance(data, dict) else data
                from gitgrounded.mcp.introspect import _tool_dict

                tools = [_tool_dict(t) for t in tools]
            else:
                tools = load_tools_file(variant.root / self.cfg.tools_file)
        else:
            tools = self.client(variant).list_tools()
        self._tools[variant.content_hash] = tools
        return tools

    def invoke(self, case: Case, variant: Variant, trial: int) -> Transcript:
        request: dict[str, Any] = {"task": case.input_text()}
        start = time.perf_counter()
        try:
            tools = self.tools(variant)
            explicit = case.context.get("tool_call") if isinstance(case.context, dict) else None
            if explicit:
                choice = {"tool": explicit.get("name"), "arguments": explicit.get("arguments", {})}
            else:
                provider = build_provider(self.cfg.agent or ProviderCfg())
                user = json.dumps({"task": case.input_text(), "tools": tools}, ensure_ascii=False)
                choice, _ = complete_json(
                    provider, SELECT_SYSTEM, user, task="tool_select", meta={"task": case.input_text(), "tools": tools}
                )
            request["selected"] = choice
            name = choice.get("tool")
            args = choice.get("arguments") or {}
            result_text, is_error = "", False
            if name and not self.cfg.tools_file:
                fixtures = case.context.get("fixtures", {}) if isinstance(case.context, dict) else {}
                if name in fixtures:
                    result_text = fixtures[name] if isinstance(fixtures[name], str) else json.dumps(fixtures[name])
                    request["sandboxed"] = True
                else:
                    result_text, is_error = self.client(variant).call_tool(name, args)
        except Exception as e:
            return error_transcript(case, variant, trial, request, f"{type(e).__name__}: {e}")
        output = {"tool": name, "arguments": args, "result": result_text, "is_error": is_error}
        return Transcript(
            case_id=case.id,
            variant=variant.name,
            trial=trial,
            request=request,
            raw_output=json.dumps(output, ensure_ascii=False, sort_keys=True),
            output=output,
            tool_calls=[ToolCall(name=name, arguments=args, result=result_text)] if name else [],
            latency_ms=(time.perf_counter() - start) * 1000,
        )
