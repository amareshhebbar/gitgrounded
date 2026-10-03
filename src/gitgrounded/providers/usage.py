import threading
from collections import defaultdict
from typing import Any

from gitgrounded.errors import BudgetExceeded
from gitgrounded.stats.cost import tokens_cost


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
            self.prices = dict(prices or {})
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

    def check(self) -> None:
        if self.budget_usd is not None and self.cost() > self.budget_usd:
            raise BudgetExceeded(f"budget of ${self.budget_usd:.2f} exceeded (spent ${self.cost():.4f})")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            models = {k: dict(v) for k, v in self.by_model.items()}
        return {"models": models, "cost_usd": round(self.cost(), 6), "budget_usd": self.budget_usd}

    def reset(self) -> None:
        with self._lock:
            self.by_model.clear()


USAGE = UsageTracker()
