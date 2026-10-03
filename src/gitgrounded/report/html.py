import difflib
import html
import json
import re
from importlib import resources
from typing import Any

from jinja2 import Environment, select_autoescape
from markupsafe import Markup

from gitgrounded.report.model import RunResult

TOKEN = re.compile(r"\s+|\w+|[^\w\s]")


def word_diff(a: str, b: str, limit: int = 6000) -> Markup:
    a, b = (a or "")[:limit], (b or "")[:limit]
    ta, tb = TOKEN.findall(a), TOKEN.findall(b)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(html.escape("".join(ta[i1:i2])))
        if op in ("delete", "replace"):
            out.append("<del>" + html.escape("".join(ta[i1:i2])) + "</del>")
        if op in ("insert", "replace"):
            out.append("<ins>" + html.escape("".join(tb[j1:j2])) + "</ins>")
    return Markup("".join(out))


def pretty(value: Any) -> str:
    if isinstance(value, str):
        try:
            return json.dumps(json.loads(value), indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return value
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def fmt(v: Any, digits: int = 2) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def pct(v: Any) -> str:
    return "n/a" if v is None else f"{100 * float(v):.0f}%"


def _env() -> Environment:
    env = Environment(autoescape=select_autoescape(["html", "j2"]), trim_blocks=True, lstrip_blocks=True)
    env.filters["fmt"] = fmt
    env.filters["pct"] = pct
    env.filters["pretty"] = pretty
    env.globals["word_diff"] = word_diff
    return env


def _read(name: str) -> str:
    return resources.files("gitgrounded.report").joinpath("templates", name).read_text(encoding="utf-8")


def _template(name: str):
    return _env().from_string(_read(name))


def _css() -> Markup:
    return Markup(_read("style.css"))


def _diff_lines(diff: str) -> list[tuple[str, str]]:
    out = []
    for line in (diff or "").splitlines()[:2000]:
        kind = "ctx"
        if line.startswith("+") and not line.startswith("+++"):
            kind = "add"
        elif line.startswith("-") and not line.startswith("---"):
            kind = "del"
        elif line.startswith(("@@", "diff ", "index ", "+++", "---")):
            kind = "meta"
        out.append((kind, line))
    return out


def render_html(result: RunResult, provenance: dict[str, Any] | None = None) -> str:
    rows = []
    order = {"FAIL": 0, "BROKEN": 1, "WARN": 2, "UNSTABLE": 3, "IMPROVED": 4, "PASS": 5}
    for r in sorted(result.cases, key=lambda r: (order.get(r["status"], 9), r["delta"].get("score", 0.0))):
        head_t = r["head"]["trials"][0] if r["head"]["trials"] else None
        base_t = r["base"]["trials"][0] if r["base"] and r["base"]["trials"] else None
        head_out = (head_t["transcript"].get("raw_output") or head_t["transcript"].get("error") or "") if head_t else ""
        base_out = (base_t["transcript"].get("raw_output") or base_t["transcript"].get("error") or "") if base_t else ""
        rows.append(
            {
                "r": r,
                "head_t": head_t,
                "base_t": base_t,
                "head_out": pretty(head_out),
                "base_out": pretty(base_out),
                "diff": word_diff(pretty(base_out), pretty(head_out)) if base_t else None,
                "score_head": r["head"]["scores"].get("score"),
                "score_base": r["base"]["scores"].get("score") if r["base"] else None,
            }
        )
    metrics = [(k, v) for k, v in result.metrics.items() if k != "assertion_pass_rate"]
    return _template("report.html.j2").render(
        res=result,
        rows=rows,
        metrics=metrics,
        apr=result.metrics.get("assertion_pass_rate", {}),
        diff_lines=_diff_lines(result.diff),
        provenance=provenance or {},
        coverage=result.coverage,
        css=_css(),
    )


def render_coverage_html(
    suite: str,
    meta: dict[str, Any],
    coverage: dict[str, Any],
    mutation: dict[str, Any] | None,
    dims: dict[str, list[str]],
    logs: dict | None,
) -> str:
    return _template("coverage.html.j2").render(
        suite=suite, meta=meta, cov=coverage, mutation=mutation or {}, dims=dims, logs=logs or {}, css=_css()
    )
