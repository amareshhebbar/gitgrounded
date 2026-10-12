import os
import threading
from collections import defaultdict
from typing import Any

from gitgrounded.errors import BudgetExceeded
from gitgrounded.stats.cost import env_price_overrides, has_price, tokens_cost


class UsageTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.by_model: dict[str, dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        )
        self.prices: dict[str, list[float]] = {}
        self.budget_usd: float | None = None

    def configure(self, prices: dict[str, list[float]], budget_usd: float | None) -> None:
        with self._lock:
            self.prices = {**dict(prices or {}), **env_price_overrides()}
            self.budget_usd = budget_usd

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            m = self.by_model[model or "unknown"]
            m["calls"] += 1
            m["input_tokens"] += int(input_tokens or 0)
            m["output_tokens"] += int(output_tokens or 0)

    def cost(self) -> float:
        with self._lock:
            return sum(
                tokens_cost(k, v["input_tokens"], v["output_tokens"], self.prices) for k, v in self.by_model.items()
            )

    def unpriced_models(self) -> list[str]:
        with self._lock:
            return sorted(
                k
                for k, v in self.by_model.items()
                if k != "mock" and (v["input_tokens"] or v["output_tokens"]) and not has_price(k, self.prices)
            )

    def check(self) -> None:
        if self.budget_usd is not None and os.environ.get("GITGROUNDED_ALLOW_UNKNOWN_COST", "") != "1":
            unknown = self.unpriced_models()
            if unknown:
                raise BudgetExceeded(
                    f"cannot enforce the budget: no price known for {', '.join(unknown)}. "
                    "Add it to prices in gitgrounded.yml, set GITGROUNDED_PRICES, or set GITGROUNDED_ALLOW_UNKNOWN_COST=1"
                )
        if self.budget_usd is not None and self.cost() > self.budget_usd:
            raise BudgetExceeded(f"budget of ${self.budget_usd:.2f} exceeded (spent ${self.cost():.4f})")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            models = {k: dict(v) for k, v in self.by_model.items()}
        return {
            "models": models,
            "cost_usd": round(self.cost(), 6),
            "budget_usd": self.budget_usd,
            "unpriced_models": self.unpriced_models(),
        }

    def reset(self) -> None:
        with self._lock:
            self.by_model.clear()


USAGE = UsageTracker()
