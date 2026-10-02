import importlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from gitgrounded.cases.model import Case
from gitgrounded.jsonpath import jsonpath_get_all
from gitgrounded.providers.heuristics import REFUSAL_OUTPUT
from gitgrounded.targets.base import Transcript


@dataclass
class AssertionResult:
    type: str
    passed: bool
    message: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AssertionFn = Callable[[Transcript, dict[str, Any], Case], AssertionResult]
REGISTRY: dict[str, AssertionFn] = {}
_BASE_DIR: list[Path] = [Path.cwd()]


def set_base_dir(path: Path) -> None:
    _BASE_DIR[0] = path


def register(name: str):
    def deco(fn: AssertionFn) -> AssertionFn:
        REGISTRY[name] = fn
        return fn

    return deco


def _ok(t: str, cond: bool, msg_fail: str, msg_ok: str = "ok") -> AssertionResult:
    return AssertionResult(t, bool(cond), msg_ok if cond else msg_fail)


def _texts(tr: Transcript, params: dict[str, Any]) -> list[str]:
    path = params.get("path")
    if path:
        data = tr.parsed_json()
        if data is None:
            return []
        return [v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in jsonpath_get_all(data, path)]
    return [tr.text()]


@register("json_valid")
def a_json_valid(tr, params, case):
    return _ok("json_valid", tr.parsed_json() is not None, "output is not valid JSON")


@register("json_schema")
def a_json_schema(tr, params, case):
    import jsonschema

    data = tr.parsed_json()
    if data is None:
        return AssertionResult("json_schema", False, "output is not valid JSON")
    schema = params.get("schema")
    if isinstance(schema, str):
        p = Path(schema)
        p = p if p.is_absolute() else _BASE_DIR[0] / p
        schema = json.loads(p.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(data, schema)
        return AssertionResult("json_schema", True, "ok")
    except jsonschema.ValidationError as e:
        loc = "/".join(str(x) for x in e.absolute_path) or "$"
        return AssertionResult("json_schema", False, f"{loc}: {e.message}")


@register("jsonpath_exists")
def a_jsonpath_exists(tr, params, case):
    data = tr.parsed_json()
    vals = jsonpath_get_all(data, params["path"]) if data is not None else []
    return _ok("jsonpath_exists", bool(vals), f"{params['path']} not found")


@register("jsonpath_equals")
def a_jsonpath_equals(tr, params, case):
    data = tr.parsed_json()
    vals = jsonpath_get_all(data, params["path"]) if data is not None else []
    expected = params.get("value")
    return _ok(
        "jsonpath_equals",
        bool(vals) and vals[0] == expected,
        f"{params['path']} = {vals[0] if vals else None!r}, expected {expected!r}",
    )


@register("one_of")
def a_one_of(tr, params, case):
    data = tr.parsed_json()
    vals = jsonpath_get_all(data, params["path"]) if data is not None else []
    allowed = params.get("values", [])
    v = vals[0] if vals else None
    return _ok("one_of", v in allowed, f"{params['path']} = {v!r} not in {allowed}")


@register("non_empty")
def a_non_empty(tr, params, case):
    texts = _texts(tr, params)
    return _ok(
        "non_empty",
        any(t.strip() and t.strip().lower() not in ("null", '""') for t in texts),
        f"{params.get('path', 'output')} is empty",
    )


@register("contains")
def a_contains(tr, params, case):
    texts = " ".join(_texts(tr, params))
    needles = params.get("values") or [params.get("value", "")]
    cs = params.get("case_sensitive", False)
    hay = texts if cs else texts.lower()
    missing = [n for n in needles if (n if cs else n.lower()) not in hay]
    if params.get("any"):
        return _ok("contains", len(missing) < len(needles), f"none of {needles} found")
    return _ok("contains", not missing, f"missing {missing}")


@register("not_contains")
def a_not_contains(tr, params, case):
    texts = " ".join(_texts(tr, params))
    needles = params.get("values") or [params.get("value", "")]
    cs = params.get("case_sensitive", False)
    hay = texts if cs else texts.lower()
    found = [n for n in needles if n and (n if cs else n.lower()) in hay]
    return _ok("not_contains", not found, f"found forbidden {found}")


@register("regex")
def a_regex(tr, params, case):
    texts = " ".join(_texts(tr, params))
    flags = 0 if params.get("case_sensitive", False) else re.I
    found = re.search(params["pattern"], texts, flags) is not None
    if params.get("negate"):
        return _ok("regex", not found, f"pattern {params['pattern']!r} matched")
    return _ok("regex", found, f"pattern {params['pattern']!r} not matched")


@register("max_length")
def a_max_length(tr, params, case):
    text = " ".join(_texts(tr, params))
    unit = params.get("unit", "chars")
    n = len(text.split()) if unit == "words" else len(text)
    limit = int(params.get("value", params.get("max", 0)))
    return _ok("max_length", n <= limit, f"{n} {unit} > {limit}")


@register("latency_ms_below")
def a_latency(tr, params, case):
    limit = float(params.get("value", 0))
    return _ok("latency_ms_below", tr.latency_ms <= limit, f"latency {tr.latency_ms:.0f}ms > {limit:.0f}ms")


@register("cost_below")
def a_cost(tr, params, case):
    from gitgrounded.stats.cost import transcript_cost

    limit = float(params.get("value", 0))
    cost = transcript_cost(tr, params.get("prices") or {})
    return _ok("cost_below", cost <= limit, f"cost {cost:.5f} > {limit}")


@register("refusal")
def a_refusal(tr, params, case):
    return _ok("refusal", REFUSAL_OUTPUT.search(tr.text()) is not None, "expected a refusal")


@register("not_refusal")
def a_not_refusal(tr, params, case):
    return _ok("not_refusal", REFUSAL_OUTPUT.search(tr.text()) is None, "unexpected refusal")


@register("tool_called")
def a_tool_called(tr, params, case):
    names = [c.name for c in tr.tool_calls]
    tool = params.get("tool") or params.get("value")
    return _ok("tool_called", tool in names, f"tool {tool} not called (called {names})")


@register("tool_not_called")
def a_tool_not_called(tr, params, case):
    names = [c.name for c in tr.tool_calls]
    tool = params.get("tool") or params.get("value")
    return _ok("tool_not_called", tool not in names, f"tool {tool} was called")


@register("tool_call_order")
def a_tool_order(tr, params, case):
    names = [c.name for c in tr.tool_calls]
    expected = params.get("tools", [])
    it = iter(names)
    ok = all(any(n == e for n in it) for e in expected)
    return _ok("tool_call_order", ok, f"expected order {expected}, got {names}")


@register("max_steps")
def a_max_steps(tr, params, case):
    limit = int(params.get("value", 0))
    return _ok("max_steps", len(tr.tool_calls) <= limit, f"{len(tr.tool_calls)} tool calls > {limit}")


@register("no_error")
def a_no_error(tr, params, case):
    return _ok("no_error", not tr.error, f"target error: {(tr.error or '')[:300]}")


@register("python")
def a_python(tr, params, case):
    module, _, fn_name = params["function"].partition(":")
    fn = getattr(importlib.import_module(module), fn_name)
    res = fn(tr.to_dict(), case.model_dump(mode="json"), params)
    if isinstance(res, AssertionResult):
        return res
    if isinstance(res, tuple):
        return AssertionResult("python", bool(res[0]), str(res[1]) if len(res) > 1 else "")
    return AssertionResult("python", bool(res), "ok" if res else "python assertion failed")


def _load_plugins() -> None:
    try:
        eps = entry_points(group="gitgrounded.assertions")
    except TypeError:
        eps = []
    for ep in eps:
        if ep.name not in REGISTRY:
            try:
                REGISTRY[ep.name] = ep.load()
            except Exception:
                continue


_load_plugins()


def run_assertions(specs: list[dict[str, Any]], tr: Transcript, case: Case) -> list[AssertionResult]:
    results = []
    if tr.error:
        return [AssertionResult("no_error", False, f"target error: {tr.error[:300]}")]
    for spec in specs:
        spec = dict(spec)
        t = spec.get("type", "")
        fn = REGISTRY.get(t)
        label = spec.get("label") or t
        if fn is None:
            results.append(AssertionResult(t, False, f"unknown assertion type '{t}'", label))
            continue
        try:
            r = fn(tr, spec, case)
        except Exception as e:
            r = AssertionResult(t, False, f"assertion error: {type(e).__name__}: {e}")
        r.label = label
        results.append(r)
    return results


def oracle_assertions(case: Case) -> list[dict[str, Any]]:
    out = []
    for e in case.expectations:
        if e.kind == "tool_call" and e.tool:
            out.append({"type": "tool_called", "tool": e.tool, "label": f"oracle:{e.behavior_id or 'tool'}"})
    return out
