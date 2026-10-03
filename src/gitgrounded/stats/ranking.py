from typing import Any

VERDICT_RANK = {"FAIL": 2, "WARN": 1, "PASS": 0}


def _ci_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("ci_lower") is None or b.get("ci_lower") is None:
        return False
    return not (a["ci_upper"] < b["ci_lower"] or b["ci_upper"] < a["ci_lower"])


def rank_results(results: list[tuple[str, dict[str, Any]]], metric: str = "score") -> list[dict[str, Any]]:
    def key(item):
        name, s = item
        head = s.get("metrics", {}).get(metric, {}).get("head", {})
        return (
            VERDICT_RANK.get(s.get("verdict", "FAIL"), 2),
            s.get("counts", {}).get("head_assertion_failures", 0),
            -(s.get("pairwise", {}).get("head_win_rate") or 0.0),
            -(head.get("mean") or 0.0),
        )

    ordered = sorted(results, key=key)
    out = []
    for i, (name, s) in enumerate(ordered):
        head = s.get("metrics", {}).get(metric, {}).get("head", {})
        tied_with = []
        for other_name, other in ordered:
            if other_name == name:
                continue
            oh = other.get("metrics", {}).get(metric, {}).get("head", {})
            if other.get("verdict") == s.get("verdict") and _ci_overlap(head, oh):
                tied_with.append(other_name)
        out.append(
            {
                "rank": i + 1,
                "name": name,
                "verdict": s.get("verdict"),
                "mean": head.get("mean"),
                "ci_lower": head.get("ci_lower"),
                "ci_upper": head.get("ci_upper"),
                "head_win_rate": s.get("pairwise", {}).get("head_win_rate"),
                "assertion_failures": s.get("counts", {}).get("head_assertion_failures", 0),
                "tied_with": tied_with,
            }
        )
    return out
