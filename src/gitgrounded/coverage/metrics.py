from typing import Any

from gitgrounded.cases.model import Case
from gitgrounded.coverage.extract import Behavior
from gitgrounded.coverage.planner import tuple_coverage


def compute_coverage(
    behaviors: list[Behavior],
    plans: dict[str, dict],
    cases: list[Case],
    strength: int,
    min_cases: int,
    mutation: dict | None = None,
    diversity: dict | None = None,
    logs: dict | None = None,
) -> dict[str, Any]:
    by_behavior: dict[str, list[Case]] = {b.id: [] for b in behaviors}
    for c in cases:
        for bid in c.behaviors:
            by_behavior.setdefault(bid, []).append(c)
    rows = []
    total_cov, total_req = 0, 0
    heat: dict[str, dict[str, dict[str, int]]] = {}
    kills: dict[str, int] = {}
    survived: dict[str, int] = {}
    for m in (mutation or {}).get("mutants", []):
        for bid in m.get("behavior_ids", []):
            if m.get("killed"):
                kills[bid] = kills.get(bid, 0) + 1
            else:
                survived[bid] = survived.get(bid, 0) + 1
    for b in behaviors:
        group = by_behavior.get(b.id, [])
        p = plans.get(b.id, {})
        dims = p.get("dims", {})
        cov, req = tuple_coverage([c.cell for c in group], dims, strength) if dims else (0, 0)
        total_cov += cov
        total_req += req
        heat[b.id] = {}
        for c in group:
            for dname, val in c.cell.items():
                heat[b.id].setdefault(dname, {})
                heat[b.id][dname][val] = heat[b.id][dname].get(val, 0) + 1
        rows.append(
            {
                "id": b.id,
                "kind": b.kind,
                "severity": b.severity,
                "statement": b.statement,
                "source_ids": b.source_ids,
                "source_text": b.source_text,
                "implicit": b.implicit,
                "cases": len(group),
                "reviewed": sum(1 for c in group if c.reviewed),
                "tuple_coverage": (cov / req) if req else None,
                "mutants_killed": kills.get(b.id, 0),
                "mutants_survived": survived.get(b.id, 0),
                "diversity": (diversity or {}).get(b.id, {}).get("diversity"),
            }
        )
    covered = sum(1 for r in rows if r["cases"] >= min_cases)
    reviewed = sum(1 for c in cases if c.reviewed)
    summary = {
        "behaviors": len(behaviors),
        "behaviors_covered": covered,
        "behavior_coverage": covered / len(behaviors) if behaviors else None,
        "cases": len(cases),
        "cases_by_origin": {o: sum(1 for c in cases if c.origin == o) for o in ("human", "synth", "log", "diff")},
        "tuple_coverage": total_cov / total_req if total_req else None,
        "strength": strength,
        "min_cases_per_behavior": min_cases,
        "reviewed_fraction": reviewed / len(cases) if cases else 0.0,
        "mutation_score": (mutation or {}).get("score"),
        "mutants": len((mutation or {}).get("mutants", [])),
        "untested_traffic_clusters": len((logs or {}).get("untested_traffic", [])),
    }
    return {"summary": summary, "behaviors": rows, "heatmap": heat}
