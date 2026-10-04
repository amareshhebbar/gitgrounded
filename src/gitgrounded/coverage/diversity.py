import re

import numpy as np

from gitgrounded.cases.model import Case


def shingles(text: str, n: int = 5) -> set[str]:
    t = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if len(t) <= n:
        return {t}
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def remove_near_duplicates(cases: list[Case], threshold: float = 0.8) -> tuple[list[Case], list[str]]:
    kept: list[Case] = []
    kept_sh: list[set[str]] = []
    removed: list[str] = []
    for c in cases:
        sh = shingles(c.input_text())
        if any(jaccard(sh, k) >= threshold for k in kept_sh):
            removed.append(c.id)
            continue
        kept.append(c)
        kept_sh.append(sh)
    return kept, removed


def mmr_select(cases: list[Case], vectors: np.ndarray, k: int, lam: float = 0.7) -> list[int]:
    n = len(cases)
    if n <= k:
        return list(range(n))
    rel = np.asarray([float(c.meta.get("realistic", 0.5)) for c in cases])
    sims = vectors @ vectors.T
    chosen: list[int] = []
    baseline = [i for i, c in enumerate(cases) if c.meta.get("baseline")]
    chosen.append(baseline[0] if baseline else int(np.argmax(rel)))
    remaining = set(range(n)) - set(chosen)
    while len(chosen) < k and remaining:
        best, best_score = None, -1e9
        for i in sorted(remaining):
            score = lam * rel[i] - (1 - lam) * max(sims[i, j] for j in chosen)
            if score > best_score:
                best, best_score = i, score
        chosen.append(best)
        remaining.discard(best)
    return chosen


def diversity_score(vectors: np.ndarray) -> float | None:
    n = len(vectors)
    if n < 2:
        return None
    sims = vectors @ vectors.T
    iu = np.triu_indices(n, k=1)
    return float(1.0 - sims[iu].mean())


def select_diverse(
    cases_by_behavior: dict[str, list[Case]],
    targets: dict[str, int],
    embedder,
    lam: float = 0.7,
    dup_threshold: float = 0.8,
) -> tuple[list[Case], dict[str, dict]]:
    final: list[Case] = []
    stats: dict[str, dict] = {}
    for bid, group in cases_by_behavior.items():
        deduped, removed = remove_near_duplicates(group, dup_threshold)
        if not deduped:
            stats[bid] = {"generated": len(group), "near_duplicates": len(removed), "selected": 0, "diversity": None}
            continue
        vecs = embedder.embed([c.input_text() for c in deduped])
        idx = mmr_select(deduped, vecs, targets.get(bid, len(deduped)), lam)
        chosen = [deduped[i] for i in idx]
        final += chosen
        stats[bid] = {
            "generated": len(group),
            "near_duplicates": len(removed),
            "selected": len(chosen),
            "diversity": diversity_score(vecs[idx]) if len(idx) > 1 else None,
        }
    return final, stats
