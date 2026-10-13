import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "triage" / "make_demo_repo.py"

EXPECT = {
    "same": "PASS",
    "test/safe-wording-tweak": "PASS",
    "test/drop-citation-rule": "FAIL",
    "test/drop-policy-field": "FAIL",
    "test/remove-grounding": "FAIL",
    "test/model-downgrade": "FAIL",
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def parse_roles(items: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in items:
        role, _, spec = item.partition("=")
        provider, _, model = spec.partition(":")
        if role not in ("judge", "generator", "validator") or not provider or not model:
            sys.exit(f"bad --role '{item}', use judge=groq:openai/gpt-oss-120b")
        out[role] = {"provider": provider, "model": model}
    return out


def make_repo(dest: Path, roles: dict[str, dict[str, str]]) -> Path:
    src = dest / "example"
    shutil.copytree(DEMO.parent, src, ignore=shutil.ignore_patterns(".gitgrounded", "__pycache__", ".git"))
    if roles:
        cfg_path = src / "gitgrounded.yml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        for role, spec in roles.items():
            cfg.setdefault("providers", {}).setdefault(role, {}).update(spec)
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    repo = dest / "demo"
    subprocess.run(
        [sys.executable, str(src / "make_demo_repo.py"), str(repo)], check=True, capture_output=True, text=True
    )
    return repo


def run_once(repo: Path, head: str, out: Path, trials: int | None, budget: float | None) -> dict:
    cmd = ["gitgrounded", "run", "--base", "baseline", "--head", "baseline" if head == "same" else head]
    cmd += ["--fail-on", "never", "--json-out", str(out), "--no-generate"]
    if trials:
        cmd += ["--trials", str(trials)]
    if budget:
        cmd += ["--budget-usd", str(budget)]
    started = time.time()
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    if not out.exists():
        return {"head": head, "error": (proc.stderr or proc.stdout)[-500:], "seconds": time.time() - started}
    data = json.loads(out.read_text(encoding="utf-8"))
    return {
        "head": head,
        "verdict": data["verdict"],
        "usd": data.get("cost", {}).get("run_usd"),
        "regressions": data["counts"].get("regressions"),
        "unstable": data["counts"].get("unstable_cases"),
        "seconds": round(time.time() - started, 1),
    }


def summarize(rows: list[dict], reps: int) -> tuple[list[str], dict]:
    lines = [
        "| comparison | expected | runs | matched | rate | 95% interval |",
        "|---|---|---|---|---|---|",
    ]
    stats = {}
    for head, want in EXPECT.items():
        sub = [r for r in rows if r["head"] == head and "verdict" in r]
        matched = sum(1 for r in sub if r["verdict"] == want)
        lo, hi = wilson(matched, len(sub))
        rate = matched / len(sub) if sub else 0.0
        stats[head] = {"expected": want, "runs": len(sub), "matched": matched, "rate": rate, "low": lo, "high": hi}
        lines.append(f"| {head} | {want} | {len(sub)} | {matched} | {rate:.0%} | {lo:.0%} to {hi:.0%} |")
    return lines, stats


def main() -> None:
    ap = argparse.ArgumentParser(description="measure false alarm rate, detection rate and cost with real models")
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument("--budget-usd", type=float, default=2.0)
    ap.add_argument("--out", default=str(ROOT / "bench" / "results"))
    ap.add_argument("--allow-offline", action="store_true")
    ap.add_argument(
        "--role", action="append", default=[], help="override a role, for example judge=groq:openai/gpt-oss-120b"
    )
    args = ap.parse_args()
    offline = os.environ.get("GITGROUNDED_OFFLINE", "0") == "1"
    if offline and not args.allow_offline:
        sys.exit(
            "GITGROUNDED_OFFLINE is set; unset it and export real provider keys, or pass --allow-offline to test the plumbing"
        )
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(Path(td), parse_roles(args.role))
        for rep in range(args.reps):
            for head in EXPECT:
                out = Path(td) / f"r-{rep}-{head.replace('/', '_')}.json"
                row = run_once(repo, head, out, args.trials, args.budget_usd)
                row["rep"] = rep
                rows.append(row)
                print(f"rep {rep} {head}: {row.get('verdict', 'ERROR')} {row.get('usd')}", file=sys.stderr)
    lines, stats = summarize(rows, args.reps)
    total = sum(r.get("usd") or 0 for r in rows)
    errors = [r for r in rows if "error" in r]
    header = [
        "# Validation results",
        "",
        f"created {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, repetitions {args.reps}"
        + (", OFFLINE MOCK, not a real result" if offline else ""),
        "",
    ]
    footer = ["", f"total spend USD {total:.2f}, runs with errors {len(errors)}"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps({"stats": stats, "rows": rows, "offline": offline}, indent=2))
    (out / "validation.md").write_text("\n".join(header + lines + footer) + "\n", encoding="utf-8")
    print("\n".join(header + lines + footer))


if __name__ == "__main__":
    main()
