import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ["GITGROUNDED_OFFLINE"] = "1"


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("GITGROUNDED_OFFLINE", "1")
    monkeypatch.setenv("GITGROUNDED_SIGNING_KEY", str(tmp_path / "keys" / "ed25519.pem"))
    from gitgrounded.providers.base import reset_provider_cache
    from gitgrounded.providers.usage import USAGE

    reset_provider_cache()
    USAGE.reset()
    yield


@pytest.fixture
def demo_repo(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    dest = tmp_path / "demo"
    subprocess.run(
        [sys.executable, str(ROOT / "examples" / "triage" / "make_demo_repo.py"), str(dest)],
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(dest)
    return dest


@pytest.fixture
def engine(demo_repo):
    from gitgrounded.config.loader import load_config
    from gitgrounded.engine import Engine
    from gitgrounded.project import find_project

    project = find_project(demo_repo)
    eng = Engine(project, load_config(project.config_path))
    yield eng
    eng.close()
