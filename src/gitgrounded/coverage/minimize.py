from gitgrounded.cases.model import Case


def greedy_minimize(cases: list[Case], kills: dict[str, set[str]], min_per_behavior: int) -> list[str]:
    universe = set().union(*kills.values()) if kills else set()
    chosen: list[str] = []
    covered: set[str] = set()
    remaining = {c.id: set(kills.get(c.id, set())) for c in cases}
    while covered != universe:
        best = max(remaining, key=lambda cid: (len(remaining[cid] - covered), cid), default=None)
        if best is None or not (remaining[best] - covered):
            break
        chosen.append(best)
        covered |= remaining.pop(best)
    per_behavior: dict[str, int] = {}
    by_id = {c.id: c for c in cases}
    for cid in chosen:
        for b in by_id[cid].behaviors:
            per_behavior[b] = per_behavior.get(b, 0) + 1
    for c in cases:
        if c.id in chosen:
            continue
        need = [b for b in c.behaviors if per_behavior.get(b, 0) < min_per_behavior]
        if need or (not c.behaviors and c.origin == "human"):
            chosen.append(c.id)
            for b in c.behaviors:
                per_behavior[b] = per_behavior.get(b, 0) + 1
    order = {c.id: i for i, c in enumerate(cases)}
    return sorted(set(chosen), key=lambda cid: order[cid])
