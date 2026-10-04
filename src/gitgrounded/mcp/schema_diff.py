import difflib
import re
from typing import Any

BREAKING = "breaking"
RISKY = "risky"
SAFE = "safe"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _type_set(schema: dict[str, Any]) -> set[str]:
    t = schema.get("type")
    if isinstance(t, list):
        return set(t)
    if isinstance(t, str):
        return {t}
    if "anyOf" in schema or "oneOf" in schema:
        out: set[str] = set()
        for s in schema.get("anyOf", []) + schema.get("oneOf", []):
            out |= _type_set(s)
        return out
    return set()


def _change(level: str, tool: str, kind: str, detail: str) -> dict[str, str]:
    return {"level": level, "tool": tool, "kind": kind, "detail": detail}


def diff_params(tool: str, old: dict[str, Any], new: dict[str, Any], desc_threshold: float) -> list[dict[str, str]]:
    changes = []
    old_props = (old or {}).get("properties", {}) or {}
    new_props = (new or {}).get("properties", {}) or {}
    old_req = set((old or {}).get("required", []) or [])
    new_req = set((new or {}).get("required", []) or [])
    for p in sorted(set(old_props) - set(new_props)):
        changes.append(_change(BREAKING, tool, "param_removed", f"parameter '{p}' removed"))
    for p in sorted(set(new_props) - set(old_props)):
        if p in new_req:
            changes.append(_change(BREAKING, tool, "required_param_added", f"new required parameter '{p}'"))
        else:
            changes.append(_change(SAFE, tool, "optional_param_added", f"new optional parameter '{p}'"))
    for p in sorted(new_req - old_req):
        if p in old_props:
            changes.append(_change(BREAKING, tool, "param_now_required", f"parameter '{p}' became required"))
    for p in sorted(old_req - new_req):
        if p in new_props:
            changes.append(_change(SAFE, tool, "param_now_optional", f"parameter '{p}' became optional"))
    for p in sorted(set(old_props) & set(new_props)):
        o, n = old_props[p] or {}, new_props[p] or {}
        ot, nt = _type_set(o), _type_set(n)
        if ot and nt and ot != nt:
            level = BREAKING if not ot <= nt else SAFE
            changes.append(
                _change(level, tool, "param_type_changed", f"parameter '{p}' type {sorted(ot)} -> {sorted(nt)}")
            )
        oe, ne = set(map(str, o.get("enum", []) or [])), set(map(str, n.get("enum", []) or []))
        if oe and ne:
            removed = oe - ne
            added = ne - oe
            if removed:
                changes.append(
                    _change(BREAKING, tool, "enum_value_removed", f"parameter '{p}' enum removed {sorted(removed)}")
                )
            if added:
                changes.append(_change(SAFE, tool, "enum_value_added", f"parameter '{p}' enum added {sorted(added)}"))
        elif ne and not oe:
            changes.append(_change(BREAKING, tool, "enum_added", f"parameter '{p}' now restricted to {sorted(ne)}"))
        od, nd = o.get("description", ""), n.get("description", "")
        if _norm(od) != _norm(nd):
            sim = _similarity(od, nd)
            level = RISKY if sim < desc_threshold else SAFE
            changes.append(
                _change(
                    level,
                    tool,
                    "param_description_changed",
                    f"parameter '{p}' description changed (similarity {sim:.2f})",
                )
            )
    return changes


def diff_tools(
    old_tools: list[dict[str, Any]],
    new_tools: list[dict[str, Any]],
    desc_threshold: float = 0.85,
    overlap_threshold: float = 0.6,
) -> dict[str, Any]:
    old = {t["name"]: t for t in old_tools}
    new = {t["name"]: t for t in new_tools}
    changes: list[dict[str, str]] = []
    removed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    renamed: dict[str, str] = {}
    for r in removed:
        for a in added:
            if a in renamed.values():
                continue
            if _similarity(old[r].get("description", ""), new[a].get("description", "")) > 0.9:
                renamed[r] = a
                break
    for r in removed:
        if r in renamed:
            changes.append(_change(BREAKING, r, "tool_renamed", f"tool '{r}' renamed to '{renamed[r]}'"))
        else:
            changes.append(_change(BREAKING, r, "tool_removed", f"tool '{r}' removed"))
    for a in added:
        if a in renamed.values():
            continue
        overlaps = [
            n
            for n in old
            if n in new
            and _similarity(new[a].get("description", ""), old[n].get("description", "")) > overlap_threshold
        ]
        if overlaps:
            changes.append(
                _change(
                    RISKY,
                    a,
                    "tool_added_overlapping",
                    f"new tool '{a}' overlaps with {overlaps}; models may pick the wrong one",
                )
            )
        else:
            changes.append(_change(SAFE, a, "tool_added", f"new tool '{a}'"))
    for name in sorted(set(old) & set(new)):
        o, n = old[name], new[name]
        od, nd = o.get("description", ""), n.get("description", "")
        if _norm(od) != _norm(nd):
            sim = _similarity(od, nd)
            level = RISKY if sim < desc_threshold else SAFE
            changes.append(_change(level, name, "description_changed", f"description changed (similarity {sim:.2f})"))
        changes += diff_params(name, o.get("inputSchema", {}), n.get("inputSchema", {}), desc_threshold)
    additive = {
        "tool_added",
        "tool_added_overlapping",
        "optional_param_added",
        "enum_value_added",
        "param_now_optional",
    }
    if any(c["level"] == BREAKING for c in changes):
        bump = "major"
    elif any(c["level"] == RISKY or c["kind"] in additive for c in changes):
        bump = "minor"
    elif changes:
        bump = "patch"
    else:
        bump = "none"
    return {
        "changes": changes,
        "summary": {
            "breaking": sum(1 for c in changes if c["level"] == BREAKING),
            "risky": sum(1 for c in changes if c["level"] == RISKY),
            "safe": sum(1 for c in changes if c["level"] == SAFE),
            "semver": bump,
        },
    }
