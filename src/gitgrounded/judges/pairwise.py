import json
from dataclasses import asdict, dataclass, field
from typing import Any

from gitgrounded.cases.model import Case
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.store.cache import Cache
from gitgrounded.targets.base import Transcript

PAIRWISE_SYSTEM = """You compare two outputs (A and B) of the same AI application for the same user input.
Decide which output better satisfies the case expectations, stays grounded in the provided context, follows the application's rules, and helps the user.
Ignore length and style unless an expectation is about them. If they are equally good or equally bad, answer tie.
Return JSON: {"winner": "A" | "B" | "tie", "reason": "<one or two sentences>"}"""


@dataclass
class PairwiseResult:
    winner: str
    consistent: bool
    orders: list[str] = field(default_factory=list)
    reason: str = ""
    model: str | None = None
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PairwiseJudge:
    name = "pairwise"

    def __init__(self, provider_cfg: ProviderCfg, cache: Cache, swap: bool = True):
        self.cfg = provider_cfg
        self.cache = cache
        self.swap = swap

    def _one(self, case: Case, a: str, b: str, context: str) -> tuple[str, str, str | None, bool]:
        payload = {"user_input": case.input_text(), "A": a[:8000], "B": b[:8000]}
        if context:
            payload["context"] = context[:12000]
        if case.expectations:
            payload["expectations"] = [f"{e.kind}: {e.text}" for e in case.expectations]
        if case.reference:
            payload["reference_answer"] = case.reference
        key = self.cache.key("pairwise", self.cfg.model_dump(mode="json"), payload)
        hit = self.cache.get("judge", key)
        if hit is not None:
            return hit["winner"], hit["reason"], hit.get("model"), True
        if a == b:
            res = {"winner": "tie", "reason": "identical outputs", "model": None}
        else:
            provider = build_provider(self.cfg)
            data, comp = complete_json(
                provider,
                PAIRWISE_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                task="judge_pairwise",
                meta={
                    "a": a,
                    "b": b,
                    "expectations": [e.text for e in case.expectations],
                    "reference": case.reference,
                    "input": case.input_text(),
                },
            )
            w = str(data.get("winner", "tie")).strip().upper() if isinstance(data, dict) else "TIE"
            w = {"A": "A", "B": "B"}.get(w, "tie")
            res = {"winner": w, "reason": str(data.get("reason", ""))[:600], "model": comp.model}
        self.cache.set("judge", key, res)
        return res["winner"], res["reason"], res.get("model"), False

    def compare(self, case: Case, base: Transcript, head: Transcript, context: str) -> PairwiseResult:
        bt = base.text() if not base.error else f"[error] {base.error[:300]}"
        ht = head.text() if not head.error else f"[error] {head.error[:300]}"
        w1, r1, m1, c1 = self._one(case, bt, ht, context)
        first = {"A": "base", "B": "head"}.get(w1, "tie")
        if not self.swap:
            return PairwiseResult(first, True, [first], r1, m1, c1)
        w2, r2, m2, c2 = self._one(case, ht, bt, context)
        second = {"A": "head", "B": "base"}.get(w2, "tie")
        if first == second:
            return PairwiseResult(first, True, [first, second], r1, m1, c1 and c2)
        return PairwiseResult("tie", False, [first, second], f"order dependent: {r1} | {r2}", m1, c1 and c2)
