import json

from gitgrounded.cases.model import Case
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.store.cache import Cache

DIFF_SYSTEM = """You write regression test inputs for an AI application. You receive a unified diff of the application's prompt, configuration or tool definitions, a short description of the domain, and examples of existing test inputs.
Write realistic user inputs that are most likely to reveal a behavior change caused by exactly this diff: inputs where the removed or added instruction decides the answer, boundary values of changed numbers, and requests that a weakened rule would now let through.
Do not repeat existing inputs. Vary phrasing, length and tone.
Return JSON: {"cases": [{"id": "diff-1", "input": "...", "expectation": "what a correct answer must do, based on the OLD behavior unless the diff intentionally changes it"}]}"""


def generate_diff_cases(
    provider_cfg: ProviderCfg, cache: Cache, diff: str, domain: str, existing: list[Case], count: int
) -> list[Case]:
    if not diff.strip() or count <= 0:
        return []
    samples = [c.input_text() for c in existing[:8]]
    payload = {"diff": diff[:20000], "domain": domain, "existing_inputs": samples, "count": count}
    key = cache.key("diff_cases", provider_cfg.model_dump(mode="json"), payload)
    hit = cache.get("generate", key)
    if hit is None:
        provider = build_provider(provider_cfg)
        data, _ = complete_json(
            provider,
            DIFF_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            task="diff_cases",
            meta={"diff": diff, "count": count, "domain": domain},
        )
        hit = data.get("cases", []) if isinstance(data, dict) else []
        cache.set("generate", key, hit)
    existing_inputs = {c.input_text().strip().lower() for c in existing}
    out = []
    for i, row in enumerate(hit[:count]):
        if not isinstance(row, dict) or not row.get("input"):
            continue
        text = row["input"] if isinstance(row["input"], str) else json.dumps(row["input"])
        if text.strip().lower() in existing_inputs:
            continue
        exps = [{"kind": "must", "text": row["expectation"]}] if row.get("expectation") else []
        out.append(Case(id=f"diff-{i + 1:03d}", input=row["input"], origin="diff", tags=["diff"], expectations=exps))
    return out
