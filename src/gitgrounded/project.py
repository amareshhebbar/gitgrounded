import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAMES = ("gitgrounded.yml", "gitgrounded.yaml")


@dataclass(frozen=True)
class Project:
    root: Path
    config_path: Path | None
    state_dir: Path

    @property
    def cache_dir(self) -> Path:
        return self.state_dir / "cache"

    @property
    def history_dir(self) -> Path:
        return self.state_dir / "history"

    @property
    def runs_dir(self) -> Path:
        return self.state_dir / "runs"

    @property
    def suites_dir(self) -> Path:
        return self.state_dir / "suites"

    @property
    def worktrees_dir(self) -> Path:
        return self.state_dir / "worktrees"

    @property
    def mutants_dir(self) -> Path:
        return self.state_dir / "mutants"

    def resolve(self, path: str | os.PathLike) -> Path:
        p = Path(path).expanduser()
        return p if p.is_absolute() else (self.root / p).resolve()

    def rel(self, path: str | os.PathLike) -> str:
        p = Path(path).resolve()
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return p.as_posix()

    def with_state_dir(self, state_dir: str) -> "Project":
        return Project(self.root, self.config_path, self.resolve(state_dir))


def git_toplevel(start: Path) -> Path | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def find_project(start: Path | None = None, config: str | None = None) -> Project:
    if config:
        cfg = Path(config).expanduser().resolve()
        return Project(cfg.parent, cfg if cfg.exists() else None, cfg.parent / ".gitgrounded")
    start = (start or Path.cwd()).resolve()
    for d in [start, *start.parents]:
        for name in CONFIG_NAMES:
            candidate = d / name
            if candidate.is_file():
                return Project(d, candidate, d / ".gitgrounded")
    root = git_toplevel(start) or start
    return Project(root, None, root / ".gitgrounded")
