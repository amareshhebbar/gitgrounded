import math
from collections import Counter

import numpy as np


def cohen_kappa(a: list, b: list) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for x, y in pairs if x == y) / n
    ca = Counter(x for x, _ in pairs)
    cb = Counter(y for _, y in pairs)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1 - pe)


def _rank(values: np.ndarray) -> np.ndarray:
    order = values.argsort(kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(len(values), dtype=float)
    sorted_vals = values[order]
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        if j > i:
            avg = (i + j) / 2.0
            ranks[order[i : j + 1]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    x = _rank(np.asarray([p[0] for p in pairs], dtype=float))
    y = _rank(np.asarray([p[1] for p in pairs], dtype=float))
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def krippendorff_alpha_interval(ratings: list[list[float | None]]) -> float | None:
    mat = np.asarray([[np.nan if v is None else float(v) for v in row] for row in ratings], dtype=float)
    if mat.ndim != 2 or mat.shape[0] < 2:
        return None
    units = [mat[:, j][~np.isnan(mat[:, j])] for j in range(mat.shape[1])]
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None
    n = sum(len(u) for u in units)
    do = 0.0
    for u in units:
        m = len(u)
        diffs = (u[:, None] - u[None, :]) ** 2
        do += diffs.sum() / (m - 1)
    do /= n
    allv = np.concatenate(units)
    de = ((allv[:, None] - allv[None, :]) ** 2).sum() / (n * (n - 1))
    if de == 0:
        return 1.0
    return float(1 - do / de)


def position_consistency(flags: list[bool]) -> float | None:
    if not flags:
        return None
    return sum(1 for f in flags if f) / len(flags)


def safe_float(x) -> float | None:
    try:
        f = float(x)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None
