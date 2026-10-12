import json
import os
from datetime import date

DEFAULT_PRICES = {"mock": [0.0, 0.0]}
PRICES_UPDATED = "2026-10-04"
PRICES_STALE_DAYS = 60


def prices_age_days(today: date | None = None) -> int:
    y, m, d = (int(x) for x in PRICES_UPDATED.split("-"))
    return ((today or date.today()) - date(y, m, d)).days


def env_price_overrides() -> dict[str, list[float]]:
    raw = os.environ.get("GITGROUNDED_PRICES", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    out: dict[str, list[float]] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                try:
                    out[str(k)] = [float(v[0]), float(v[1])]
                except (TypeError, ValueError):
                    continue
    return out


def has_price(model: str | None, prices: dict[str, list[float]]) -> bool:
    if not model:
        return False
    m = model.lower()
    return any(key.lower() in m for key in prices)


def price_for(model: str | None, prices: dict[str, list[float]]) -> tuple[float, float]:
    if not model:
        return 0.0, 0.0
    m = model.lower()
    best = None
    for key, val in prices.items():
        if key.lower() in m and (best is None or len(key) > len(best[0])):
            best = (key, val)
    if best is None:
        return 0.0, 0.0
    return float(best[1][0]), float(best[1][1])


def transcript_cost(tr, prices: dict[str, list[float]]) -> float:
    pin, pout = price_for(tr.model, prices or DEFAULT_PRICES)
    return (tr.input_tokens * pin + tr.output_tokens * pout) / 1_000_000


def tokens_cost(model: str | None, input_tokens: int, output_tokens: int, prices: dict[str, list[float]]) -> float:
    pin, pout = price_for(model, prices or DEFAULT_PRICES)
    return (input_tokens * pin + output_tokens * pout) / 1_000_000
