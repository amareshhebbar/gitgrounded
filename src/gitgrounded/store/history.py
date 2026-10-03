import json
import re
import shutil
import time
from pathlib import Path
from typing import Any


def safe_label(label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip()).strip("_") or "default"


class History:
    def __init__(self, root: Path):
        self.root = root

    def dir_for(self, label: str) -> Path:
        return self.root / safe_label(label)

    def versions(self, label: str) -> list[int]:
        d = self.dir_for(label)
        if not d.is_dir():
            return []
        nums = []
        for p in d.iterdir():
            m = re.match(r"^v(\d+)\.json$", p.name)
            if m:
                nums.append(int(m.group(1)))
        return sorted(nums)

    def latest(self, label: str) -> int | None:
        v = self.versions(label)
        return v[-1] if v else None

    def save(self, label: str, data: dict[str, Any]) -> int:
        d = self.dir_for(label)
        d.mkdir(parents=True, exist_ok=True)
        n = (self.latest(label) or 0) + 1
        payload = dict(data)
        payload.setdefault("saved_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        payload["version"] = n
        (d / f"v{n}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return n

    def load(self, label: str, n: int) -> dict[str, Any]:
        return json.loads((self.dir_for(label) / f"v{n}.json").read_text(encoding="utf-8"))

    def delete(self, label: str, n: int | None = None) -> int:
        d = self.dir_for(label)
        if not d.is_dir():
            return 0
        if n is None:
            count = len(self.versions(label))
            shutil.rmtree(d)
            return count
        p = d / f"v{n}.json"
        if p.exists():
            p.unlink()
            return 1
        return 0

    def delete_all(self) -> int:
        if not self.root.is_dir():
            return 0
        count = len([p for p in self.root.iterdir() if p.is_dir()])
        shutil.rmtree(self.root)
        return count

    def labels(self) -> list[tuple[str, int]]:
        if not self.root.is_dir():
            return []
        return [(p.name, self.latest(p.name) or 0) for p in sorted(self.root.iterdir()) if p.is_dir()]
