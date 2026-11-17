import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(HERE / "work" / "triage-bench"))
    ap.add_argument("--only", default=None, help="comma separated scenario names")
    ap.add_argument("--max", type=int, default=0, help="run at most this many scenarios per group")
    ap.add_argument("--trials", type=int, default=int(os.environ.get("GG_TRIALS", 1)))
    ap.add_argument("--budget-usd", type=float, default=float(os.environ.get("GG_RUN_BUDGET_USD", 0.5)))
    ap.add_argument("--rerun", action="store_true")
    args = ap.parse_args()
    if os.environ.get("GITGROUNDED_OFFLINE") == "1" and os.environ.get("ALLOW_OFFLINE") != "1":
        sys.exit("GITGROUNDED_OFFLINE=1 is set. Offline mock runs are not real results. Unset it, or set ALLOW_OFFLINE=1 for a plumbing test.")
    repo = Path(args.repo)
    plan = kit.read_jsonl(HERE / "results" / "scenarios.jsonl")
    if args.only:
        keep = set(args.only.split(","))
        plan = [p for p in plan if p["name"] in keep]
    if args.max:
        seen = {}
        cut = []
        for p in plan:
            g = p["name"].split("-")[0]
            seen[g] = seen.get(g, 0) + 1
            if seen[g] <= args.max:
                cut.append(p)
        plan = cut
    out_dir = HERE / "results" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in plan:
        out = out_dir / f"{p['name']}.json"
        if out.exists() and not args.rerun:
            print(f"[skip] {p['name']} already done")
            continue
        if p["name"].startswith("null-"):
            shutil.rmtree(repo / ".gitgrounded" / "cache", ignore_errors=True)
        cmd = ["gitgrounded", "run", "--base", "baseline", "--head", p["branch"], "--suite", "core",
               "--no-generate", "--fail-on", "never", "--json-out", str(out), "--trials", str(args.trials),
               "--format", "json"]
        if args.budget_usd:
            cmd += ["--budget-usd", str(args.budget_usd)]
        started = time.time()
        proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        seconds = round(time.time() - started, 1)
        meta = {"name": p["name"], "expect": p["expect"], "seconds": seconds, "exit_code": proc.returncode,
                "command": " ".join(cmd)}
        if not out.exists():
            meta["error"] = (proc.stderr or proc.stdout)[-2000:]
            kit.write_json(out_dir / f"{p['name']}.error.json", meta)
            print(f"[error] {p['name']}: {meta['error'][-300:]}")
            continue
        (out_dir / f"{p['name']}.error.json").unlink(missing_ok=True)
        data = json.loads(out.read_text(encoding="utf-8"))
        data["_bench"] = meta
        out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        print(f"[done] {p['name']}: expected {p['expect']}, got {data.get('verdict')} in {seconds}s, "
              f"cost {data.get('cost', {}).get('run_usd')}", flush=True)


if __name__ == "__main__":
    main()
