import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP = shutil.ignore_patterns(".gitgrounded", "__pycache__", "make_demo_repo.py", ".git")

SCENARIOS = {
    "test/safe-wording-tweak": ("prompts/triage.txt", "mid-sized SaaS company", "mid-size SaaS company"),
    "test/drop-citation-rule": (
        "prompts/triage.txt",
        "Always cite the exact policy line you relied on.",
        "Keep your answer as short as possible.",
    ),
    "test/model-downgrade": ("config/model.yaml", "openai/gpt-oss-120b", "openai/gpt-oss-20b"),
}


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="create a throwaway git repo with the triage demo branches")
    parser.add_argument("dest", nargs="?", default="gitgrounded-triage-demo")
    args = parser.parse_args()
    dest = Path(args.dest).resolve()
    if dest.exists():
        sys.exit(f"{dest} already exists")
    shutil.copytree(HERE, dest, ignore=SKIP)
    git(["init", "-q", "-b", "baseline"], dest)
    git(["config", "user.email", "demo@gitgrounded.local"], dest)
    git(["config", "user.name", "gitgrounded demo"], dest)
    git(["add", "-A"], dest)
    git(["commit", "-q", "-m", "baseline"], dest)
    for branch, (rel, old, new) in SCENARIOS.items():
        git(["checkout", "-q", "-b", branch, "baseline"], dest)
        p = dest / rel
        text = p.read_text(encoding="utf-8")
        if old not in text:
            sys.exit(f"scenario {branch}: '{old}' not found in {rel}")
        p.write_text(text.replace(old, new), encoding="utf-8")
        git(["commit", "-q", "-am", branch], dest)
    git(["checkout", "-q", "baseline"], dest)
    print(f"demo repo ready at {dest}")
    print(f"cd {dest}")
    print("export GITGROUNDED_OFFLINE=1")
    print("gitgrounded run --base baseline --head test/drop-citation-rule")


if __name__ == "__main__":
    main()
