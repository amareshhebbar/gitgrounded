import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gitgrounded.cases.loader import load_cases, write_cases  # noqa: E402
from gitgrounded.config.loader import load_config  # noqa: E402
from gitgrounded.coverage.pipeline import CoveragePipeline  # noqa: E402
from gitgrounded.coverage.suite_store import SuiteStore  # noqa: E402
from gitgrounded.engine import Engine  # noqa: E402
from gitgrounded.project import find_project  # noqa: E402
from gitgrounded.providers.base import is_offline  # noqa: E402

EXAMPLES = {"triage": {"auto": "auto", "hand_cases": "data/cases.jsonl"}}


def score_suite(engine: Engine, name: str, mutants: int) -> dict:
    pipe = CoveragePipeline(engine, name, log=lambda m: print(f"  {m}", file=sys.stderr))
    m = pipe.mutate(repair=False, max_mutants=mutants)
    ops: dict[str, dict[str, int]] = {}
    for r in m["mutants"]:
        if r.get("equivalent"):
            continue
        o = ops.setdefault(r["operator"], {"killed": 0, "total": 0})
        o["total"] += 1
        o["killed"] += int(r["killed"])
    return {
        "suite": name,
        "cases": len(pipe.store.cases()),
        "killed": m["killed"],
        "total": m["total"],
        "score": m["score"],
        "equivalent": m["equivalent"],
        "by_operator": ops,
    }


def run(example: str, mutants: int, out: Path) -> dict:
    spec = EXAMPLES[example]
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / example
        shutil.copytree(ROOT / "examples" / example, work, ignore=shutil.ignore_patterns(".gitgrounded", "__pycache__"))
        project = find_project(work)
        cfg = load_config(project.config_path)
        engine = Engine(project, cfg)
        auto = spec["auto"]
        print(f"[{example}] synthesizing auto suite", file=sys.stderr)
        CoveragePipeline(engine, auto, log=lambda m: print(f"  {m}", file=sys.stderr)).synth(incremental=False)
        cfg.suites["hand"] = cfg.suites[auto].model_copy()
        src, dst = SuiteStore(engine.project, auto), SuiteStore(engine.project, "hand")
        dst.dir.mkdir(parents=True, exist_ok=True)
        for f in ("behavior_map.json", "plan.json", "dimensions.json"):
            shutil.copy2(src.path(f), dst.path(f))
        hand = load_cases(work / spec["hand_cases"])
        write_cases(dst.path("current.jsonl"), hand)
        dst.write_json("suite.json", {"suite": "hand", "version": "hand"})
        dst.write_cases(hand)
        results = [score_suite(engine, auto, mutants), score_suite(engine, "hand", mutants)]
        engine.close()
    report = {
        "example": example,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "offline": is_offline(),
        "judge": cfg.providers.judge.model,
        "generator": cfg.providers.generator.model,
        "results": results,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{example}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"# Reference benchmark: {example}",
        "",
        f"generator {report['generator']}, judge {report['judge']}{' (OFFLINE MOCK, not a real result)' if report['offline'] else ''}",
        "",
        "| suite | cases | planted faults detected | score | equivalent (excluded) |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        sc = "n/a" if r["score"] is None else f"{r['score']:.0%}"
        lines.append(f"| {r['suite']} | {r['cases']} | {r['killed']}/{r['total']} | {sc} | {r['equivalent']} |")
    lines += ["", "| operator | auto | hand |", "|---|---|---|"]
    ops = sorted(set(results[0]["by_operator"]) | set(results[1]["by_operator"]))
    for o in ops:
        a = results[0]["by_operator"].get(o, {"killed": 0, "total": 0})
        h = results[1]["by_operator"].get(o, {"killed": 0, "total": 0})
        lines.append(f"| {o} | {a['killed']}/{a['total']} | {h['killed']}/{h['total']} |")
    (out / f"{example}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="measure how many planted regressions auto generated and hand written suites detect"
    )
    ap.add_argument("--example", default="triage", choices=sorted(EXAMPLES))
    ap.add_argument("--mutants", type=int, default=30)
    ap.add_argument("--out", default=str(ROOT / "bench" / "results"))
    args = ap.parse_args()
    run(args.example, args.mutants, Path(args.out))


if __name__ == "__main__":
    main()
