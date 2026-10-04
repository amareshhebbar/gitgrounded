import json
from typing import Any

from gitgrounded.cases.model import Case
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.coverage.extract import Behavior
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.store.cache import Cache

VALIDATE_SYSTEM = """You audit generated test cases for an AI application before they enter a benchmark.
For each case you get the user input, the behavior it is meant to test (with the exact source text), and the expectations a correct answer must meet.
Score each case:
- realistic: 0 to 1, how plausible this is as a real user message.
- targets_behavior: true if the behavior actually decides the correct response for this input.
- expectation_consistent: true only if every expectation follows from the behavior's source text. False if any expectation invents a rule, number or policy, or contradicts the source.
- answerable: true if a correct response is possible from the application's instructions and documents.
Return JSON: {"results": [{"id": "...", "realistic": 0.0, "targets_behavior": true, "expectation_consistent": true, "answerable": true, "note": "..."}]}"""


def validate_cases(
    provider_cfg: ProviderCfg, cache: Cache, cases: list[Case], behaviors: dict[str, Behavior], batch: int = 12
) -> tuple[list[Case], list[dict[str, Any]]]:
    kept: list[Case] = []
    dropped: list[dict[str, Any]] = []
    provider = None
    for i in range(0, len(cases), batch):
        chunk = cases[i : i + batch]
        items = []
        for c in chunk:
            b = behaviors.get(c.behaviors[0]) if c.behaviors else None
            items.append(
                {
                    "id": c.id,
                    "input": c.input_text(),
                    "behavior": b.statement if b else "",
                    "source_text": b.source_text if b else "",
                    "expectations": [f"{e.kind}: {e.text}" for e in c.expectations],
                }
            )
        key = cache.key("validate", provider_cfg.model_dump(mode="json"), items)
        rows = cache.get("coverage", key)
        if rows is None:
            provider = provider or build_provider(provider_cfg)
            data, _ = complete_json(
                provider,
                VALIDATE_SYSTEM,
                json.dumps({"cases": items}, ensure_ascii=False),
                task="validate",
                meta={"cases": items},
            )
            rows = data.get("results", []) if isinstance(data, dict) else []
            cache.set("coverage", key, rows)
        by_id = {r.get("id"): r for r in rows if isinstance(r, dict)}
        for c in chunk:
            r = by_id.get(c.id)
            if r is None:
                c.meta["realistic"] = 0.5
                c.meta["validated"] = False
                kept.append(c)
                continue
            ok = (
                bool(r.get("targets_behavior", True))
                and bool(r.get("expectation_consistent", True))
                and bool(r.get("answerable", True))
            )
            try:
                c.meta["realistic"] = float(r.get("realistic", 0.5))
            except (TypeError, ValueError):
                c.meta["realistic"] = 0.5
            c.meta["validated"] = True
            if ok:
                kept.append(c)
            else:
                dropped.append(
                    {
                        "id": c.id,
                        "input": c.input_text(),
                        "reason": r.get("note") or "failed validation",
                        "flags": {k: r.get(k) for k in ("targets_behavior", "expectation_consistent", "answerable")},
                    }
                )
    return kept, dropped
