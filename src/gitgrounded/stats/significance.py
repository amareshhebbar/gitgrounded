import itertools
import math

import numpy as np


def paired_bootstrap_delta(
    base: list[float], head: list[float], iterations: int = 5000, seed: int = 1234, alpha: float = 0.05
) -> dict[str, float | None]:
    pairs = [
        (b, h) for b, h in zip(base, head) if b is not None and h is not None and not (math.isnan(b) or math.isnan(h))
    ]
    if not pairs:
        return {"mean": None, "ci_lower": None, "ci_upper": None, "n": 0}
    d = np.asarray([h - b for b, h in pairs], dtype=float)
    n = len(d)
    mean = float(d.mean())
    if n == 1:
        return {"mean": mean, "ci_lower": mean, "ci_upper": mean, "n": 1}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(iterations, n))
    means = d[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return {"mean": mean, "ci_lower": float(lo), "ci_upper": float(hi), "n": n}


def sign_flip_p_value(deltas: list[float], iterations: int = 10000, seed: int = 1234) -> float | None:
    d = np.asarray([x for x in deltas if x is not None and not math.isnan(x)], dtype=float)
    n = len(d)
    if n == 0:
        return None
    observed = abs(d.mean())
    if observed == 0:
        return 1.0
    if n <= 16:
        total = 0
        hits = 0
        for signs in itertools.product((1.0, -1.0), repeat=n):
            total += 1
            if abs((d * np.asarray(signs)).mean()) >= observed - 1e-12:
                hits += 1
        return hits / total
    rng = np.random.default_rng(seed)
    signs = rng.choice([1.0, -1.0], size=(iterations, n))
    stats = np.abs((signs * d).mean(axis=1))
    return float((np.sum(stats >= observed - 1e-12) + 1) / (iterations + 1))


def holm(pvalues: dict[str, float | None]) -> dict[str, float | None]:
    items = sorted([(k, v) for k, v in pvalues.items() if v is not None], key=lambda kv: kv[1])
    m = len(items)
    adjusted: dict[str, float | None] = {k: None for k in pvalues}
    running = 0.0
    for i, (k, p) in enumerate(items):
        val = min(1.0, (m - i) * p)
        running = max(running, val)
        adjusted[k] = running
    return adjusted
