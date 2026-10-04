import asyncio
import json
import os
from pathlib import Path
from typing import Any

from gitgrounded.errors import TargetError


def _tool_dict(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        d = tool
    else:
        try:
            d = tool.model_dump(mode="json", by_alias=True)
        except Exception:
            d = {"name": getattr(tool, "name", ""), "description": getattr(tool, "description", "")}
    schema = d.get("inputSchema") or d.get("input_schema") or d.get("parameters") or {}
    return {"name": d.get("name", ""), "description": d.get("description") or "", "inputSchema": schema}


def _result_text(result: Any) -> tuple[str, bool]:
    content = getattr(result, "content", None) or []
    parts = []
    for c in content:
        text = getattr(c, "text", None)
        parts.append(
            text if text is not None else json.dumps(c.model_dump(mode="json") if hasattr(c, "model_dump") else str(c))
        )
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if structured and not parts:
        parts.append(json.dumps(structured, ensure_ascii=False))
    is_error = bool(getattr(result, "is_error", False) or getattr(result, "isError", False))
    return "\n".join(parts), is_error


class McpClient:
    def __init__(
        self,
        transport: str,
        command: list[str] | None = None,
        url: str | None = None,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout_s: float = 60.0,
    ):
        self.transport = transport
        self.command = command or []
        self.url = url
        self.cwd = cwd
        self.env = env or {}
        self.timeout_s = timeout_s

    async def _with_session(self, fn):
        try:
            from mcp import ClientSession
        except ImportError as e:
            raise TargetError("install gitgrounded[mcp] to test MCP servers") from e
        if self.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, stdio_client

            if not self.command:
                raise TargetError("mcp stdio target needs a command")
            env = dict(os.environ)
            env.update(self.env)
            params = StdioServerParameters(
                command=self.command[0], args=self.command[1:], env=env, cwd=str(self.cwd) if self.cwd else None
            )
            with open(os.devnull, "w") as devnull:
                async with stdio_client(params, errlog=devnull) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        return await fn(session)
        try:
            from mcp.client.streamable_http import streamable_http_client as http_client
        except ImportError:
            from mcp.client.streamable_http import streamablehttp_client as http_client
        if not self.url:
            raise TargetError("mcp http target needs a url")
        async with http_client(self.url) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                return await fn(session)

    def _run(self, coro_fn):
        async def runner():
            return await asyncio.wait_for(self._with_session(coro_fn), timeout=self.timeout_s)

        return asyncio.run(runner())

    def list_tools(self) -> list[dict[str, Any]]:
        async def fn(session):
            res = await session.list_tools()
            return [_tool_dict(t) for t in res.tools]

        return self._run(fn)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        async def fn(session):
            res = await session.call_tool(name, arguments)
            return _result_text(res)

        return self._run(fn)


def load_tools_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tools = data.get("tools", data) if isinstance(data, dict) else data
    return [_tool_dict(t) for t in tools]
