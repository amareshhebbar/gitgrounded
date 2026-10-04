import json
import shutil
import time
from pathlib import Path
from typing import Any

from gitgrounded.canonical import content_hash
from gitgrounded.cases.loader import load_cases, write_cases
from gitgrounded.cases.model import Case, dataset_hash
from gitgrounded.coverage.extract import Behavior
from gitgrounded.project import Project

ARTIFACTS = [
    "behavior_map.json",
    "dimensions.json",
    "plan.json",
    "coverage.json",
    "mutation.json",
    "dropped.json",
    "logs.json",
    "suite.json",
    "current.jsonl",
    "minimal.jsonl",
]


class SuiteStore:
    def __init__(self, project: Project, name: str):
        self.project = project
        self.name = name
        self.dir = project.suites_dir / name.replace(":", "_")

    def path(self, name: str) -> Path:
        return self.dir / name

    def exists(self) -> bool:
        return self.path("current.jsonl").exists()

    def read_json(self, name: str, default: Any = None) -> Any:
        p = self.path(name)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, name: str, data: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path(name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def behaviors(self) -> list[Behavior]:
        data = self.read_json("behavior_map.json", {"behaviors": []})
        return [Behavior.model_validate(b) for b in data.get("behaviors", [])]

    def cases(self, minimal: bool = False) -> list[Case]:
        p = self.path("minimal.jsonl" if minimal and self.path("minimal.jsonl").exists() else "current.jsonl")
        return load_cases(p) if p.exists() else []

    def meta(self) -> dict[str, Any]:
        return self.read_json("suite.json", {}) or {}

    def versions(self) -> list[int]:
        vdir = self.dir / "versions"
        if not vdir.exists():
            return []
        return sorted(int(p.name[1:]) for p in vdir.iterdir() if p.name.startswith("v") and p.name[1:].isdigit())

    def save(
        self,
        behaviors: list[Behavior],
        dims: dict,
        plan: list[dict],
        cases: list[Case],
        coverage: dict,
        dropped: list[dict],
        extra: dict[str, Any] | None = None,
        logs: dict | None = None,
    ) -> int:
        self.dir.mkdir(parents=True, exist_ok=True)
        version = (self.versions()[-1] if self.versions() else 0) + 1
        self.write_json("behavior_map.json", {"behaviors": [b.model_dump() for b in behaviors]})
        self.write_json("dimensions.json", dims)
        self.write_json("plan.json", {"plans": plan})
        self.write_json("coverage.json", coverage)
        self.write_json("dropped.json", {"dropped": dropped})
        if logs is not None:
            self.write_json("logs.json", logs)
        for stale in ("mutation.json", "minimal.jsonl"):
            if self.path(stale).exists():
                self.path(stale).unlink()
        write_cases(self.path("current.jsonl"), cases)
        meta = {
            "suite": self.name,
            "version": f"v{version}",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cases": len(cases),
            "behaviors": len(behaviors),
            "dataset_hash": dataset_hash(cases),
            "behavior_map_hash": content_hash([b.model_dump() for b in behaviors]),
            **(extra or {}),
        }
        self.write_json("suite.json", meta)
        self.snapshot(version)
        return version

    def snapshot(self, version: int | None = None) -> int:
        version = version or (self.versions()[-1] if self.versions() else 1)
        vdir = self.dir / "versions" / f"v{version}"
        vdir.mkdir(parents=True, exist_ok=True)
        for name in ARTIFACTS:
            p = self.path(name)
            if p.exists():
                shutil.copy2(p, vdir / name)
        return version

    def write_cases(self, cases: list[Case], minimal: bool = False) -> None:
        write_cases(self.path("minimal.jsonl" if minimal else "current.jsonl"), cases)
        meta = self.meta()
        if not minimal:
            meta["cases"] = len(cases)
            meta["dataset_hash"] = dataset_hash(cases)
        else:
            meta["minimal_cases"] = len(cases)
        self.write_json("suite.json", meta)


def suite_integrity(store: "SuiteStore") -> tuple[bool, str]:
    if not store.exists():
        return False, "suite has not been generated"
    meta = store.meta()
    cases = store.cases()
    if not cases:
        return False, "suite is empty"
    if meta.get("dataset_hash") != dataset_hash(cases):
        return False, "current.jsonl was modified after generation"
    if meta.get("sealed_hash") and meta["sealed_hash"] != dataset_hash(cases):
        return False, "cases differ from the sealed set"
    human = [c.id for c in cases if c.origin == "human"]
    if human:
        return False, f"suite contains hand written cases: {human[:5]}"
    edited = [c.id for c in cases if c.meta.get("edited")]
    if edited:
        return False, f"suite contains manually edited cases: {edited[:5]}"
    return True, "sealed"


def seal(store: "SuiteStore") -> str:
    cases = store.cases()
    h = dataset_hash(cases)
    meta = store.meta()
    meta["sealed_hash"] = h
    meta["sealed"] = True
    store.write_json("suite.json", meta)
    return h
