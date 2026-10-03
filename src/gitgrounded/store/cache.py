import json
import os
import tempfile
from pathlib import Path
from typing import Any

from gitgrounded.canonical import content_hash


class Cache:
    def __init__(self, root: Path, enabled: bool = True):
        self.root = root
        self.enabled = enabled and os.environ.get("GITGROUNDED_NO_CACHE", "") not in ("1", "true")

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / key[:2] / f"{key}.json"

    def key(self, *parts: Any) -> str:
        return content_hash(list(parts))

    def get(self, namespace: str, key: str) -> Any | None:
        if not self.enabled:
            return None
        p = self._path(namespace, key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def set(self, namespace: str, key: str, value: Any) -> Any:
        if not self.enabled:
            return value
        p = self._path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
        os.replace(tmp, p)
        return value

    def clear(self) -> int:
        if not self.root.exists():
            return 0
        count = 0
        for p in self.root.rglob("*.json"):
            p.unlink()
            count += 1
        return count
