import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gitgrounded.canonical import content_hash, sha256_hex
from gitgrounded.errors import SourceError
from gitgrounded.project import Project, git_toplevel

WORKTREE_REFS = {"@worktree", "worktree", "WORKTREE", "."}
COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".gitgrounded",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
)


@dataclass
class Variant:
    name: str
    root: Path
    files: dict[str, str]
    content_hash: str
    kind: str = "git"
    ref: str | None = None
    sha: str | None = None
    overlay: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "ref": self.ref,
            "sha": self.sha,
            "content_hash": self.content_hash,
            "overlay": self.overlay,
            "files": {k: sha256_hex(v) for k, v in sorted(self.files.items())},
        }


def _git(args: list[str], cwd: Path, check: bool = True) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise SourceError("git executable not found") from e
    if check and r.returncode != 0:
        raise SourceError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def repo_info(project: Project) -> tuple[Path, str]:
    top = git_toplevel(project.root)
    if top is None:
        raise SourceError(f"{project.root} is not inside a git repository; run `git init` and commit once")
    prefix = project.root.resolve().relative_to(top.resolve()).as_posix()
    return top, "" if prefix == "." else prefix


def resolve_sha(project: Project, ref: str) -> str:
    top, _ = repo_info(project)
    out = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], top, check=False).strip()
    if not out:
        raise SourceError(f"unknown git ref '{ref}'")
    return out


def _git_path(prefix: str, rel: str) -> str:
    if rel.startswith("./"):
        rel = rel[2:]
    return f"{prefix}/{rel}" if prefix else rel


def _ensure_state_gitignore(project: Project) -> None:
    project.state_dir.mkdir(parents=True, exist_ok=True)
    gi = project.state_dir / ".gitignore"
    if not gi.exists():
        gi.write_text("cache/\nruns/\nworktrees/\nmutants/\nhistory/\n", encoding="utf-8")


def _read_watch_from_disk(root: Path, watch: list[str]) -> dict[str, str]:
    files = {}
    for rel in watch:
        p = root / rel
        if p.is_file():
            files[rel] = p.read_text(encoding="utf-8", errors="replace")
        elif p.is_dir():
            for sub in sorted(p.rglob("*")):
                if sub.is_file():
                    files[sub.relative_to(root).as_posix()] = sub.read_text(encoding="utf-8", errors="replace")
    return files


def materialize(project: Project, ref: str, watch: list[str]) -> Variant:
    if ref in WORKTREE_REFS:
        return materialize_worktree(project, watch)
    top, prefix = repo_info(project)
    sha = resolve_sha(project, ref)
    _ensure_state_gitignore(project)
    wt = project.worktrees_dir / sha[:16]
    if not (wt / ".git").exists():
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
        _git(["worktree", "prune"], top, check=False)
        wt.parent.mkdir(parents=True, exist_ok=True)
        _git(["worktree", "add", "--detach", "--force", str(wt), sha], top)
    root = wt / prefix if prefix else wt
    files = _read_watch_from_disk(root, watch)
    tree = _git(["rev-parse", f"{sha}^{{tree}}"], top).strip()
    return Variant(
        name=ref, root=root, files=files, content_hash=sha256_hex(f"tree:{tree}"), kind="git", ref=ref, sha=sha
    )


def materialize_worktree(project: Project, watch: list[str]) -> Variant:
    files = _read_watch_from_disk(project.root, watch)
    head = None
    dirty = ""
    top = git_toplevel(project.root)
    if top is not None:
        head = _git(["rev-parse", "HEAD"], top, check=False).strip() or None
        dirty = _git(["status", "--porcelain"], top, check=False) + _git(["diff", "HEAD"], top, check=False)
    return Variant(
        name="@worktree",
        root=project.root,
        files=files,
        content_hash=content_hash({"head": head, "dirty": sha256_hex(dirty), "files": files}),
        kind="worktree",
        ref="@worktree",
        sha=head,
    )


def diff_text(project: Project, base: Variant, head: Variant, watch: list[str]) -> str:
    if base.kind in ("git", "worktree") and head.kind in ("git", "worktree") and base.sha:
        try:
            top, prefix = repo_info(project)
        except SourceError:
            return _file_diff(base.files, head.files)
        paths = [_git_path(prefix, w) for w in watch] or ([prefix] if prefix else ["."])
        args = ["diff", base.sha]
        if head.kind == "git" and head.sha:
            args.append(head.sha)
        return _git([*args, "--", *paths], top, check=False)
    return _file_diff(base.files, head.files)


def _file_diff(a: dict[str, str], b: dict[str, str]) -> str:
    import difflib

    out = []
    for path in sorted(set(a) | set(b)):
        if a.get(path) == b.get(path):
            continue
        out += difflib.unified_diff(
            (a.get(path) or "").splitlines(keepends=True),
            (b.get(path) or "").splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    return "".join(out)


def derive_variant(
    project: Project,
    base: Variant,
    name: str,
    overrides: dict[str, str],
    overlay: dict[str, Any] | None = None,
    copy_tree: bool = True,
) -> Variant:
    files = dict(base.files)
    files.update(overrides)
    ch = content_hash({"base": base.content_hash, "overrides": overrides, "overlay": overlay or {}})
    root = base.root
    if copy_tree and overrides:
        _ensure_state_gitignore(project)
        root = project.mutants_dir / ch[:16]
        if not root.exists():
            tmp = root.with_name(root.name + f".tmp{os.getpid()}")
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            shutil.copytree(base.root, tmp, ignore=COPY_IGNORE, symlinks=True)
            for rel, content in overrides.items():
                p = tmp / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            try:
                tmp.rename(root)
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
    return Variant(
        name=name,
        root=root,
        files=files,
        content_hash=ch,
        kind="mutant",
        ref=base.ref,
        sha=base.sha,
        overlay=dict(overlay or {}),
    )


def overlay_variant(project: Project, name: str, overlay: dict[str, Any], watch: list[str]) -> Variant:
    files = _read_watch_from_disk(project.root, watch)
    return Variant(
        name=name,
        root=project.root,
        files=files,
        content_hash=content_hash({"files": files, "overlay": overlay}),
        kind="pair",
        overlay=overlay,
    )


def cleanup_worktrees(project: Project) -> int:
    count = 0
    if project.worktrees_dir.exists():
        try:
            top, _ = repo_info(project)
        except SourceError:
            top = None
        for p in project.worktrees_dir.iterdir():
            if top is not None:
                _git(["worktree", "remove", "--force", str(p)], top, check=False)
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
            count += 1
        if top is not None:
            _git(["worktree", "prune"], top, check=False)
    if project.mutants_dir.exists():
        shutil.rmtree(project.mutants_dir, ignore_errors=True)
    return count
