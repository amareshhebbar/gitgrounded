import math

import numpy as np


def bootstrap_mean_ci(
    values: list[float], iterations: int = 5000, seed: int = 1234, alpha: float = 0.05
) -> dict[str, float | None]:
    arr = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    n = len(arr)
    if n == 0:
        return {"mean": None, "ci_lower": None, "ci_upper": None, "n": 0}
    mean = float(arr.mean())
    if n == 1:
        return {"mean": mean, "ci_lower": mean, "ci_upper": mean, "n": 1}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(iterations, n))
    means = arr[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return {"mean": mean, "ci_lower": float(lo), "ci_upper": float(hi), "n": n}


def wilson(k: int, n: int, z: float = 1.959964) -> dict[str, float | None]:
    if n <= 0:
        return {"rate": None, "ci_lower": None, "ci_upper": None, "k": k, "n": n}
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return {"rate": p, "ci_lower": lo, "ci_upper": hi, "k": k, "n": n}
