import os
import sys
import json
import shutil
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IGNORE = shutil.ignore_patterns(".venv", ".git", ".cache", "__pycache__", "*.pyc", "report.json")


def _run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)


def _setup_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    shutil.copytree(PROJECT_ROOT, repo_dir, ignore=IGNORE)

    env = os.environ.copy()
    env["GITGROUNDED_MODE"] = "test"

    _run(["git", "init"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "test"], cwd=repo_dir)
    _run(["git", "add", "-A"], cwd=repo_dir)
    _run(["git", "commit", "-m", "baseline"], cwd=repo_dir)
    _run(["git", "branch", "baseline"], cwd=repo_dir)
    _run(["git", "checkout", "-b", "change-1"], cwd=repo_dir)

    prompt_path = repo_dir / "prompts" / "triage.txt"
    original = prompt_path.read_text()
    modified = original.replace(
        "Always cite the exact policy line you relied on.",
        "Keep your answer as short as possible.",
    )
    prompt_path.write_text(modified)

    _run(["git", "commit", "-am", "change 1: drop citation instruction"], cwd=repo_dir)

    return repo_dir, env


def test_full_pipeline_runs_and_writes_report(tmp_path):
    repo_dir, env = _setup_repo(tmp_path)

    result = _run(
        [sys.executable, "gitgrounded.py", "--old", "baseline", "--new", "change-1"],
        cwd=repo_dir,
        env=env,
    )

    assert result.returncode in (0, 1), result.stderr

    report_path = repo_dir / "report.json"
    assert report_path.exists()

    report = json.loads(report_path.read_text())
    assert report["summary"]["verdict"] in ("PASS", "WARN", "FAIL")
    assert report["summary"]["total_cases"] > 0
    assert len(report["generated_cases"]) == 2
    assert "diff" in report