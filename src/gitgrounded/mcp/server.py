import json
from pathlib import Path
from typing import Any


def build_server(project_dir: Path | None = None):
    try:
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server
        except ImportError as e:
            raise SystemExit("install gitgrounded[mcp] to run the MCP server") from e

    from gitgrounded.config.loader import load_config
    from gitgrounded.engine import Engine, RunOptions
    from gitgrounded.evidence.verify import verify_bundle
    from gitgrounded.mcp.schema_diff import diff_tools
    from gitgrounded.project import find_project

    server = Server("gitgrounded")

    def _engine() -> Engine:
        project = find_project(project_dir)
        return Engine(project, load_config(project.config_path))

    @server.tool(
        description="Run a GitGrounded regression comparison between two git refs (head may be @worktree for uncommitted changes). Returns the verdict, counts and the worst cases."
    )
    def run_suite(base: str = "HEAD", head: str = "@worktree", suite: str | None = None, quick: bool = True) -> str:
        engine = _engine()
        try:
            result = engine.run_git(suite, base, head, RunOptions(quick=quick))
        finally:
            engine.close()
        worst = [
            {"id": r["case"]["id"], "status": r["status"], "reasons": r["reasons"]}
            for r in result.cases
            if r["status"] in ("FAIL", "WARN", "BROKEN")
        ][:10]
        return json.dumps({"verdict": result.verdict, "counts": result.counts, "worst": worst, "run_id": result.run_id})

    @server.tool(description="Extract the testable behaviors from the suite's system prompt and documents.")
    def discover(suite: str | None = None) -> str:
        from gitgrounded.coverage.pipeline import CoveragePipeline

        engine = _engine()
        try:
            found = CoveragePipeline(engine, suite).discover()
        finally:
            engine.close()
        return json.dumps(
            {"behaviors": [b.model_dump() for b in found["behaviors"]], "dimensions": found["dimensions"]}
        )

    @server.tool(
        description="Generate or incrementally update the benchmark suite from the system prompt and documents."
    )
    def synth_suite(suite: str | None = None) -> str:
        from gitgrounded.coverage.pipeline import CoveragePipeline

        engine = _engine()
        try:
            out = CoveragePipeline(engine, suite).synth()
        finally:
            engine.close()
        return json.dumps(out)

    @server.tool(
        description="Classify changes between two MCP tools/list payloads as breaking, risky or safe and suggest a semver bump."
    )
    def diff_mcp_tools(old_tools_json: str, new_tools_json: str) -> str:
        old = json.loads(old_tools_json)
        new = json.loads(new_tools_json)
        old = old.get("tools", old) if isinstance(old, dict) else old
        new = new.get("tools", new) if isinstance(new, dict) else new
        return json.dumps(diff_tools(old, new))

    @server.tool(description="Verify a GitGrounded evidence bundle (.ggb): hashes, merkle root and signature.")
    def verify(bundle_path: str, identity: str | None = None) -> str:
        res = verify_bundle(Path(bundle_path), identity=identity)
        return json.dumps(
            {"status": res.status, "failed": [c for c in res.checks if not c["ok"]], "signature": res.signature}
        )

    return server


def main(project_dir: str | None = None) -> Any:
    server = build_server(Path(project_dir) if project_dir else None)
    server.run()
