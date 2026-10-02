import json
from pathlib import Path

from pydantic import ValidationError

from gitgrounded.cases.model import Case
from gitgrounded.errors import ConfigError


def _coerce(raw: dict, index: int) -> dict:
    if isinstance(raw, str):
        raw = {"input": raw}
    raw = dict(raw)
    if "id" not in raw or not raw["id"]:
        raw["id"] = f"case-{index + 1:04d}"
    if "input" not in raw:
        for key in ("message", "prompt", "question", "query"):
            if key in raw:
                raw["input"] = raw.pop(key)
                break
    return raw


def load_cases(path: Path) -> list[Case]:
    if not path.exists():
        raise ConfigError(f"cases file not found: {path}")
    text = path.read_text(encoding="utf-8")
    rows: list = []
    if path.suffix == ".jsonl":
        for n, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ConfigError(f"{path}:{n}: invalid JSON: {e}") from e
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path}: invalid JSON: {e}") from e
        rows = data.get("cases", []) if isinstance(data, dict) else data
    cases: list[Case] = []
    seen: set[str] = set()
    for i, row in enumerate(rows):
        try:
            case = Case.model_validate(_coerce(row, i))
        except ValidationError as e:
            raise ConfigError(f"{path}: case {i + 1} invalid: {e.errors()[0]['msg']}") from e
        if case.id in seen:
            raise ConfigError(f"{path}: duplicate case id {case.id}")
        seen.add(case.id)
        cases.append(case)
    return cases


def write_cases(path: Path, cases: list[Case]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c.model_dump(mode="json", exclude_defaults=False), ensure_ascii=False) + "\n")
