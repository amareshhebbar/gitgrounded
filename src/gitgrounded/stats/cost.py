DEFAULT_PRICES = {"mock": [0.0, 0.0]}


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
