import itertools
import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from gitgrounded.config.schema import CoverageCfg
from gitgrounded.coverage.dimensions import dims_for_kind
from gitgrounded.coverage.extract import Behavior

SEVERITY_WEIGHT = {"critical": 3.0, "major": 2.0, "minor": 1.0}


@dataclass
class Cell:
    behavior_id: str
    index: int
    values: dict[str, str]
    baseline: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BehaviorPlan:
    behavior_id: str
    target_cases: int
    dims: dict[str, list[str]]
    cells: list[Cell] = field(default_factory=list)
    required_tuples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "behavior_id": self.behavior_id,
            "target_cases": self.target_cases,
            "dims": self.dims,
            "cells": [c.to_dict() for c in self.cells],
            "required_tuples": self.required_tuples,
        }


def _all_tuples(names: list[str], params: dict[str, list[str]], t: int) -> set[tuple]:
    out = set()
    k = len(names)
    t = min(t, k)
    for combo in itertools.combinations(range(k), t):
        for vals in itertools.product(*[range(len(params[names[i]])) for i in combo]):
            out.add((combo, vals))
    return out


def covering_array(
    params: dict[str, list[str]], strength: int = 2, seed: int = 7, candidates: int = 24
) -> list[dict[str, str]]:
    fixed = {n: v[0] for n, v in params.items() if len(v) == 1}
    names = [n for n, v in params.items() if len(v) > 1]
    if not names:
        return [dict(fixed)]
    k = len(names)
    t = max(1, min(strength, k))
    combos = list(itertools.combinations(range(k), t))
    combos_by_pos: dict[int, list[tuple]] = {i: [c for c in combos if i in c] for i in range(k)}
    uncovered = _all_tuples(names, params, t)
    rng = random.Random(seed)
    rows: list[list[int]] = []

    def covers(row: list[int]) -> set[tuple]:
        return {(c, tuple(row[i] for i in c)) for c in combos} & uncovered

    baseline = [0] * k
    rows.append(baseline)
    uncovered -= covers(baseline)
    while uncovered:
        pool = sorted(uncovered)
        best_row, best_gain = None, -1
        for attempt in range(candidates):
            seed_tuple = pool[0] if attempt == 0 else pool[rng.randrange(len(pool))]
            row: list[int | None] = [None] * k
            for i, v in zip(seed_tuple[0], seed_tuple[1]):
                row[i] = v
            order = [i for i in range(k) if row[i] is None]
            rng.shuffle(order)
            for i in order:
                best_v, best_g = 0, -1
                for v in range(len(params[names[i]])):
                    row[i] = v
                    g = 0
                    for c in combos_by_pos[i]:
                        if all(row[j] is not None for j in c) and (c, tuple(row[j] for j in c)) in uncovered:
                            g += 1
                    if g > best_g:
                        best_v, best_g = v, g
                row[i] = best_v
            full = [int(x) for x in row]
            gain = len(covers(full))
            if gain > best_gain:
                best_row, best_gain = full, gain
        rows.append(best_row)
        uncovered -= covers(best_row)
    return [dict(fixed, **{names[i]: params[names[i]][r[i]] for i in range(k)}) for r in rows]


def tuple_coverage(cells: list[dict[str, str]], params: dict[str, list[str]], strength: int = 2) -> tuple[int, int]:
    names = [n for n, v in params.items() if len(v) > 1]
    if not names:
        return 1, 1
    required = _all_tuples(names, params, strength)
    t = min(strength, len(names))
    index = {n: {v: i for i, v in enumerate(params[n])} for n in names}
    covered = set()
    for cell in cells:
        try:
            row = [index[n][cell[n]] for n in names]
        except KeyError:
            continue
        for combo in itertools.combinations(range(len(names)), t):
            key = (combo, tuple(row[i] for i in combo))
            if key in required:
                covered.add(key)
    return len(covered), len(required)


def allocate(behaviors: list[Behavior], budget: int, min_cases: int) -> dict[str, int]:
    if not behaviors:
        return {}
    total_w = sum(SEVERITY_WEIGHT.get(b.severity, 1.0) for b in behaviors)
    out = {}
    for b in behaviors:
        share = budget * SEVERITY_WEIGHT.get(b.severity, 1.0) / total_w
        out[b.id] = max(min_cases, int(round(share)))
    return out


def plan(behaviors: list[Behavior], dims: dict[str, list[str]], cfg: CoverageCfg) -> list[BehaviorPlan]:
    targets = allocate(behaviors, cfg.budget_cases, cfg.min_cases_per_behavior)
    plans = []
    for bi, b in enumerate(behaviors):
        bdims = dims_for_kind(b.kind, dims)
        rows = covering_array(bdims, cfg.strength, seed=cfg.seed + bi)
        target = targets[b.id]
        want = max(target, int(math.ceil(target * cfg.oversample)))
        if b.severity == "critical":
            want = max(want, min(len(rows), 2 * target))
        chosen = rows[:want]
        if len(chosen) < want:
            rng = random.Random(cfg.seed * 31 + bi)
            seen = {tuple(sorted(r.items())) for r in chosen}
            names = list(bdims)
            space = 1
            for n in names:
                space *= len(bdims[n])
            attempts = 0
            while len(chosen) < want and attempts < want * 20:
                attempts += 1
                row = {n: rng.choice(bdims[n]) for n in names}
                key = tuple(sorted(row.items()))
                if key in seen and len(seen) < space:
                    continue
                seen.add(key)
                chosen.append(row)
        cells = [Cell(b.id, i, row, baseline=(i == 0)) for i, row in enumerate(chosen)]
        _, required = tuple_coverage(rows, bdims, cfg.strength)
        plans.append(BehaviorPlan(b.id, target, bdims, cells, required))
    return plans
