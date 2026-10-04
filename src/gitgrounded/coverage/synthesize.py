import json
from typing import Any

from gitgrounded.cases.model import Case, Expectation
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.coverage.dimensions import describe
from gitgrounded.coverage.extract import Behavior
from gitgrounded.coverage.planner import BehaviorPlan, Cell
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.store.cache import Cache

SYNTH_SYSTEM = """You generate test inputs for an AI application, one per requested test cell.
You receive one behavior the application must have (with the exact source text it comes from), and a list of cells. Each cell fixes conditions such as style, language, difficulty, adversary type and number of turns.
For every cell write:
- input: a realistic user message (or for turns=multi, a list of 2 to 4 {"role": "user"|"assistant", "content": "..."} messages ending with a user message) that makes this behavior decide the correct response, under exactly the cell's conditions.
- expectations: 1 to 3 checks a correct response must satisfy. kind is one of must, must_not, should, refuse, tool_call, format. Expectations must follow from the behavior and its source text only. Never invent rules, numbers or policies.
- reference: a short ideal answer only when the behavior is factual knowledge; otherwise null.
Make inputs differ from each other and from the existing inputs in wording, length, scenario and details. Write like a real user, not like a tester. Do not mention the behavior or the test.
Return JSON: {"cases": [{"cell_index": <int>, "input": "...", "expectations": [{"kind": "...", "text": "..."}], "reference": null}]}"""


def _cell_payload(cell: Cell) -> dict[str, Any]:
    return {"cell_index": cell.index, "conditions": {k: f"{v} ({describe(v)})" for k, v in cell.values.items()}}


def synthesize_for_behavior(
    provider_cfg: ProviderCfg,
    cache: Cache,
    behavior: Behavior,
    bplan: BehaviorPlan,
    examples: list[str],
    existing: list[str],
    hint: str = "",
    batch: int = 10,
    start_index: int = 0,
) -> list[Case]:
    out: list[Case] = []
    provider = None
    cells = bplan.cells
    for i in range(0, len(cells), batch):
        chunk = cells[i : i + batch]
        payload = {
            "behavior": {
                "id": behavior.id,
                "kind": behavior.kind,
                "statement": behavior.statement,
                "observable": behavior.observable,
                "source_text": behavior.source_text,
                "triggers": behavior.triggers,
            },
            "cells": [_cell_payload(c) for c in chunk],
            "example_user_inputs": examples[:3],
            "existing_inputs": existing[-20:],
        }
        if hint:
            payload["focus"] = hint
        key = cache.key("synth", provider_cfg.model_dump(mode="json"), payload)
        rows = cache.get("coverage", key)
        if rows is None:
            provider = provider or build_provider(provider_cfg)
            data, _ = complete_json(
                provider,
                SYNTH_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                task="synthesize",
                meta={"behavior": behavior.model_dump(), "cells": [c.values for c in chunk]},
            )
            rows = data.get("cases", []) if isinstance(data, dict) else []
            cache.set("coverage", key, rows)
        by_index = {c.index: c for c in chunk}
        for j, row in enumerate(rows):
            if not isinstance(row, dict) or not row.get("input"):
                continue
            idx = row.get("cell_index")
            cell = by_index.get(idx) if isinstance(idx, int) else None
            if cell is None:
                cell = chunk[min(j, len(chunk) - 1)]
            exps = []
            for e in row.get("expectations") or []:
                if isinstance(e, dict) and e.get("text"):
                    kind = e.get("kind", "must")
                    if kind not in ("must", "must_not", "should", "refuse", "tool_call", "format"):
                        kind = "must"
                    exps.append(
                        Expectation(kind=kind, text=str(e["text"]), behavior_id=behavior.id, tool=e.get("tool"))
                    )
            if not exps:
                exps = [Expectation(kind="must", text=behavior.statement, behavior_id=behavior.id)]
            n = start_index + len(out) + 1
            out.append(
                Case(
                    id=f"{behavior.id}-{n:03d}",
                    input=row["input"],
                    behaviors=[behavior.id],
                    cell=dict(cell.values),
                    expectations=exps,
                    reference=row.get("reference") if isinstance(row.get("reference"), str) else None,
                    origin="synth",
                    tags=[behavior.kind, behavior.severity] + (["baseline"] if cell.baseline else []),
                    meta={"source_text": behavior.source_text, "cell_index": cell.index, "baseline": cell.baseline},
                )
            )
            existing.append(out[-1].input_text())
    return out
