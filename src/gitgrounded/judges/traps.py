import json
from typing import Any

from gitgrounded.canonical import content_hash
from gitgrounded.cases.model import Case
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.store.cache import Cache
from gitgrounded.targets.base import Transcript

OFF_TOPIC = (
    "The Great Wall of China stretches across northern China. Bananas are a good source of potassium, "
    "and the boiling point of water at sea level is 100 degrees Celsius."
)

IDEAL_SYSTEM = """You write the ideal response an AI application should give to a user message.
You are given the user message, the expectations a correct response must satisfy, and optionally a reference answer and context.
Write only the response the application should send. Satisfy every expectation exactly, invent nothing beyond the context.
Return JSON: {"answer": "..."}"""

LOW = 3.5
HIGH = 6.0


def _pick(cases: list[Case], n: int) -> list[Case]:
    eligible = [c for c in cases if c.expectations]
    eligible.sort(key=lambda c: content_hash({"trap": c.id}))
    return eligible[: max(0, n)]


def ideal_answer(case: Case, context: str, cfg: ProviderCfg, cache: Cache) -> str:
    if case.reference:
        return case.reference
    payload = {
        "user_message": case.input_text(),
        "expectations": [f"{e.kind}: {e.text}" for e in case.expectations],
        "context": context[:8000],
    }
    key = cache.key("ideal", cfg.model_dump(mode="json"), payload)
    hit = cache.get("traps", key)
    if hit is not None:
        return hit
    data, _ = complete_json(
        build_provider(cfg),
        IDEAL_SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        task="ideal_answer",
        meta={"expectations": [e.text for e in case.expectations], "input": case.input_text()},
    )
    answer = str(data.get("answer", "")) if isinstance(data, dict) else ""
    cache.set("traps", key, answer)
    return answer


def _tr(case: Case, text: str, kind: str) -> Transcript:
    return Transcript(
        case_id=f"trap:{case.id}:{kind}", variant=f"trap:{kind}", trial=0, request={}, raw_output=text, output=text
    )


def run_traps(
    cases: list[Case],
    rubric_judges: list,
    pairwise,
    generator: ProviderCfg,
    cache: Cache,
    context: str,
    n: int,
    threshold: float,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for case in _pick(cases, n):
        good = ideal_answer(case, context, generator, cache)
        samples = [("empty", "", "low"), ("off_topic", OFF_TOPIC, "low"), ("ideal", good, "high")]
        for judge in rubric_judges:
            for kind, text, want in samples:
                res = judge.evaluate(case, _tr(case, text, kind), context)
                ok = res.score <= LOW if want == "low" else res.score >= HIGH
                items.append(
                    {
                        "case_id": case.id,
                        "judge": f"{judge.name}|{res.model}",
                        "trap": kind,
                        "expected": want,
                        "score": res.score,
                        "correct": ok,
                    }
                )
        if pairwise is not None:
            pw = pairwise.compare(case, _tr(case, good, "ideal"), _tr(case, OFF_TOPIC, "off_topic"), context)
            items.append(
                {
                    "case_id": case.id,
                    "judge": "pairwise",
                    "trap": "ideal_vs_off_topic",
                    "expected": "base",
                    "winner": pw.winner,
                    "correct": pw.winner == "base",
                }
            )
    total = len(items)
    correct = sum(1 for i in items if i["correct"])
    accuracy = correct / total if total else 0.0
    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "threshold": threshold,
        "passed": total > 0 and accuracy >= threshold,
        "items": items,
    }
