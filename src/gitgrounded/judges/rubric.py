import json
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from gitgrounded.canonical import content_hash
from gitgrounded.cases.model import Case
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.errors import ConfigError
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.store.cache import Cache
from gitgrounded.targets.base import Transcript

MAX_CONTEXT_CHARS = 12000


@dataclass
class Rubric:
    name: str
    description: str
    dimensions: list[dict[str, Any]]
    show: list[str] = field(default_factory=lambda: ["context", "reference", "expectations"])

    @property
    def dimension_names(self) -> list[str]:
        return [d["name"] for d in self.dimensions]

    def hash(self) -> str:
        return content_hash(asdict(self))


def load_rubric(name_or_path: str, base_dir: Path | None = None) -> Rubric:
    p = Path(name_or_path)
    if base_dir is not None and not p.is_absolute():
        p = base_dir / p
    if p.suffix in (".yaml", ".yml") and p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    else:
        res = resources.files("gitgrounded.judges").joinpath("rubrics", f"{name_or_path}.yaml")
        if not res.is_file():
            raise ConfigError(f"unknown rubric '{name_or_path}'")
        data = yaml.safe_load(res.read_text(encoding="utf-8"))
    return Rubric(
        name=data.get("name", name_or_path),
        description=data.get("description", ""),
        dimensions=data.get("dimensions", []),
        show=data.get("show", ["context", "reference", "expectations"]),
    )


@dataclass
class JudgeResult:
    judge: str
    scores: dict[str, float]
    reason: str
    score: float
    model: str | None = None
    response_id: str | None = None
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truncate(text: str, limit: int = MAX_CONTEXT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[truncated]"


def _expectation_lines(case: Case) -> list[str]:
    return [f"{e.kind}: {e.text}" for e in case.expectations]


def rubric_system(rubric: Rubric) -> str:
    lines = [
        "You are a strict, calibrated evaluator of an AI application's output.",
        f"Rubric: {rubric.name}. {rubric.description}",
        "Score each dimension from 0 to 10 using the anchors. Judge only what is visible in the output; do not reward length.",
        "If expectations are listed, they are the oracle for this case and override general preferences.",
        "Dimensions:",
    ]
    for d in rubric.dimensions:
        anchors = d.get("anchors", {})
        anchor_text = "; ".join(f"{k}: {v}" for k, v in anchors.items())
        lines.append(f"- {d['name']}: {d.get('description', '')} Anchors: {anchor_text}")
    names = ", ".join(f'"{n}": <0-10>' for n in rubric.dimension_names)
    lines.append(
        'Return JSON: {"scores": {' + names + '}, "reason": "<one or two sentences citing the decisive evidence>"}'
    )
    return "\n".join(lines)


class RubricJudge:
    def __init__(self, rubric: Rubric, provider_cfg: ProviderCfg, cache: Cache):
        self.rubric = rubric
        self.cfg = provider_cfg
        self.cache = cache
        self.name = f"rubric:{rubric.name}"

    def evaluate(self, case: Case, tr: Transcript, context: str) -> JudgeResult:
        output = tr.text() if not tr.error else f"[target error] {tr.error[:500]}"
        payload: dict[str, Any] = {"user_input": case.input_text(), "output": _truncate(output, 8000)}
        if "context" in self.rubric.show and context:
            payload["context"] = _truncate(context)
        if "context" in self.rubric.show and tr.context:
            payload["retrieved"] = _truncate("\n---\n".join(tr.context))
        if "reference" in self.rubric.show and case.reference:
            payload["reference_answer"] = case.reference
        if "expectations" in self.rubric.show and case.expectations:
            payload["expectations"] = _expectation_lines(case)
        if tr.tool_calls:
            payload["tool_calls"] = [{"name": c.name, "arguments": c.arguments} for c in tr.tool_calls]
        key = self.cache.key("rubric", self.rubric.hash(), self.cfg.model_dump(mode="json"), payload)
        hit = self.cache.get("judge", key)
        if hit is not None:
            r = JudgeResult(**hit)
            r.cached = True
            return r
        provider = build_provider(self.cfg)
        data, comp = complete_json(
            provider,
            rubric_system(self.rubric),
            json.dumps(payload, ensure_ascii=False),
            task="judge_rubric",
            meta={
                "output": output,
                "expectations": [e.text for e in case.expectations],
                "reference": case.reference,
                "input": case.input_text(),
                "dimensions": self.rubric.dimension_names,
            },
        )
        raw_scores = data.get("scores", data) if isinstance(data, dict) else {}
        scores = {}
        for name in self.rubric.dimension_names:
            try:
                scores[name] = max(0.0, min(10.0, float(raw_scores.get(name, 0))))
            except (TypeError, ValueError):
                scores[name] = 0.0
        if tr.error:
            scores = {k: 0.0 for k in scores}
        result = JudgeResult(
            judge=self.name,
            scores=scores,
            reason=str(data.get("reason", ""))[:1000] if isinstance(data, dict) else "",
            score=round(sum(scores.values()) / len(scores), 4) if scores else 0.0,
            model=comp.model,
            response_id=comp.response_id,
        )
        self.cache.set("judge", key, result.to_dict())
        return result
