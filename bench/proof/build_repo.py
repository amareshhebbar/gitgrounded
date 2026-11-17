import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kit
from scenarios import scenarios

EXAMPLE = HERE.parents[1] / "examples" / "triage"
SKIP = shutil.ignore_patterns(".gitgrounded", "__pycache__", "make_demo_repo.py", ".git")


FIXED_DATE = "2026-11-17T00:00:00+00:00"


def git(args: list[str], cwd: Path) -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": FIXED_DATE, "GIT_COMMITTER_DATE": FIXED_DATE}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


def role(prefix: str) -> dict:
    cfg = {
        "provider": os.environ.get(f"{prefix}_PROVIDER", "custom"),
        "model": os.environ[f"{prefix}_MODEL"],
        "temperature": 0.0,
    }
    if os.environ.get(f"{prefix}_BASE_URL"):
        cfg["base_url"] = os.environ[f"{prefix}_BASE_URL"]
    if os.environ.get(f"{prefix}_KEY_ENV"):
        cfg["api_key_env"] = os.environ[f"{prefix}_KEY_ENV"]
    if os.environ.get(f"{prefix}_RPM"):
        cfg["requests_per_minute"] = float(os.environ[f"{prefix}_RPM"])
    return cfg


def apply(repo: Path, sc: dict) -> None:
    p = repo / sc["file"]
    text = p.read_text(encoding="utf-8")
    if callable(sc["old"]):
        new = sc["old"](text)
    else:
        if text.count(sc["old"]) != 1:
            sys.exit(f"{sc['name']}: expected exactly one match of {sc['old']!r} in {sc['file']}, found {text.count(sc['old'])}")
        new = text.replace(sc["old"], sc["new"])
    if new == text:
        sys.exit(f"{sc['name']}: edit changed nothing")
    p.write_text(new, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dest")
    ap.add_argument("--example", default=str(EXAMPLE))
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()
    dest = Path(args.dest).resolve()
    if dest.exists() and not args.fresh and (HERE / "results" / "scenarios.jsonl").exists():
        print(f"{dest} exists, reusing it. Pass --fresh to rebuild.")
        return
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(args.example, dest, ignore=SKIP)

    model_cfg = {
        "provider": os.environ.get("APP_PROVIDER", "custom"),
        "model": os.environ["APP_MODEL"],
        "temperature": 0,
    }
    if os.environ.get("APP_BASE_URL"):
        model_cfg["base_url"] = os.environ["APP_BASE_URL"]
    if os.environ.get("APP_KEY_ENV"):
        model_cfg["api_key_env"] = os.environ["APP_KEY_ENV"]
    (dest / "config" / "model.yaml").write_text(yaml.safe_dump(model_cfg, sort_keys=False), encoding="utf-8")

    cfg_path = dest / "gitgrounded.yml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    judge = role("GG_JUDGE")
    cfg["providers"] = {"judge": judge, "generator": judge, "validator": judge}
    cfg.setdefault("execution", {})["max_concurrency"] = int(os.environ.get("GG_CONCURRENCY", 4))
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    cases = dest / "data" / "cases.jsonl"
    base_cases = cases.read_text(encoding="utf-8").rstrip("\n") + "\n"
    cases.write_text(base_cases + (HERE / "extra_cases.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

    git(["init", "-q", "-b", "baseline"], dest)
    git(["config", "user.email", "bench@gitgrounded.local"], dest)
    git(["config", "user.name", "gitgrounded bench"], dest)
    git(["add", "-A"], dest)
    git(["commit", "-q", "-m", "baseline"], dest)
    plan = []
    for sc in scenarios():
        branch = f"bench/{sc['name']}"
        git(["checkout", "-q", "-b", branch, "baseline"], dest)
        if sc["file"] is None:
            git(["commit", "-q", "--allow-empty", "-m", sc["name"]], dest)
        else:
            apply(dest, sc)
            git(["commit", "-q", "-am", sc["name"]], dest)
        diff = git(["diff", "baseline", branch], dest)
        plan.append({"name": sc["name"], "branch": branch, "expect": sc["expect"], "diff": diff,
                     "commit": git(["rev-parse", "HEAD"], dest)})
    git(["checkout", "-q", "baseline"], dest)
    kit.write_jsonl(HERE / "results" / "scenarios.jsonl", plan)
    kit.write_json(HERE / "results" / "setup.json", {
        "app": model_cfg,
        "judge": {k: v for k, v in judge.items()},
        "cases": len(kit.read_jsonl(cases)),
        "baseline_commit": git(["rev-parse", "baseline"], dest),
        "scenarios": len(plan),
    })
    print(f"{dest}: {len(plan)} scenario branches, {len(kit.read_jsonl(cases))} cases")


if __name__ == "__main__":
    main()
