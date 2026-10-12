import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from gitgrounded.mcp.introspect import McpClient  # noqa: E402
from gitgrounded.mcp.server import build_server  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WEATHER = ROOT / "examples" / "mcp_weather"


@pytest.fixture
def weather_client():
    return McpClient("stdio", command=[sys.executable, str(WEATHER / "server.py")], cwd=WEATHER, timeout_s=60)


def test_list_tools_over_stdio(weather_client):
    tools = weather_client.list_tools()
    names = {t["name"] for t in tools}
    assert names == {"get_forecast", "get_air_quality"}
    forecast = next(t for t in tools if t["name"] == "get_forecast")
    assert "city" in forecast["inputSchema"]["properties"]
    assert "city" in forecast["inputSchema"]["required"]
    assert forecast["description"]


def test_call_tool_over_stdio(weather_client):
    text, is_error = weather_client.call_tool("get_forecast", {"city": "Mumbai", "days": 2})
    assert not is_error
    assert json.loads(text) == {"city": "Mumbai", "days": 2, "forecast": "31C, humid"}


def test_call_unknown_tool_reports_error(weather_client):
    try:
        text, is_error = weather_client.call_tool("does_not_exist", {})
    except Exception as e:
        assert "does_not_exist" in str(e) or "unknown" in str(e).lower() or "not found" in str(e).lower()
    else:
        assert is_error or "not" in text.lower()


def test_stdio_without_command_is_rejected():
    from gitgrounded.errors import TargetError

    with pytest.raises(TargetError):
        McpClient("stdio", command=[]).list_tools()


def test_http_without_url_is_rejected():
    from gitgrounded.errors import TargetError

    with pytest.raises(TargetError):
        McpClient("http").list_tools()


def test_gitgrounded_mcp_server_exposes_expected_tools():
    server = build_server()
    listing = asyncio.run(server.list_tools())
    tools = listing.tools if hasattr(listing, "tools") else listing
    names = {t.name for t in tools}
    assert {"run_suite", "discover", "synth_suite", "diff_mcp_tools", "verify"} <= names


def test_gitgrounded_mcp_diff_tool_roundtrip():
    server = build_server()
    old = [
        {
            "name": "t",
            "description": "does a thing in detail",
            "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
        }
    ]
    new = [
        {
            "name": "t",
            "description": "does a thing in detail",
            "inputSchema": {
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a", "b"],
            },
        }
    ]
    result = asyncio.run(
        server.call_tool("diff_mcp_tools", {"old_tools_json": json.dumps(old), "new_tools_json": json.dumps(new)})
    )
    text = _text(result)
    payload = json.loads(text)
    assert payload["summary"]["breaking"] == 1
    assert payload["summary"]["semver"] == "major"
    assert payload["changes"][0]["kind"] == "required_param_added"


def _text(result):
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, dict):
        return result.get("result") or json.dumps(result)
    content = getattr(result, "content", result)
    if isinstance(content, list) and content:
        first = content[0]
        return getattr(first, "text", None) or str(first)
    return str(content)


def _git(cwd, *args):
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _cli(cwd, *args):
    import os
    import subprocess

    env = dict(os.environ, GITGROUNDED_OFFLINE="1")
    return subprocess.run(
        [sys.executable, "-m", "gitgrounded", *args], cwd=cwd, capture_output=True, text=True, env=env, timeout=240
    )


def test_mcp_weather_example_end_to_end(tmp_path):
    import shutil

    work = tmp_path / "weather"
    shutil.copytree(WEATHER, work, ignore=shutil.ignore_patterns("__pycache__", ".gitgrounded"))
    cfg = work / "gitgrounded.yml"
    cfg.write_text(
        cfg.read_text().replace('command: ["python", "server.py"]', f'command: ["{sys.executable}", "server.py"]')
    )
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "v1")
    desc = work / "descriptions.json"
    desc.write_text(
        desc.read_text().replace("Get the weather forecast for a city for the next N days.", "Weather data.")
    )
    diff = _cli(work, "mcp", "diff", "--base", "HEAD")
    assert "risky" in diff.stdout and "get_forecast" in diff.stdout
    run = _cli(work, "run", "--base", "HEAD", "--format", "json")
    assert run.returncode in (0, 1), run.stderr
    result = json.loads(run.stdout)
    assert result["verdict"] in ("PASS", "WARN", "FAIL")
    assert result["counts"]["total_cases"] >= 1
