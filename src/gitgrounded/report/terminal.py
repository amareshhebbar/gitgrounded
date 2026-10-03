from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gitgrounded.report.model import RunResult

COLORS = {
    "PASS": "green",
    "WARN": "yellow",
    "FAIL": "red",
    "IMPROVED": "cyan",
    "BROKEN": "magenta",
    "UNSTABLE": "bright_black",
}


def _fmt(v: Any, digits: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def _ci(m: dict | None) -> str:
    if not m or m.get("mean") is None:
        return "-"
    return f"{m['mean']:.2f} [{m['ci_lower']:.2f}, {m['ci_upper']:.2f}]"


def _short(text: str, n: int = 140) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 3] + "..."


def render_run(result: RunResult, console: Console | None = None, top: int = 5) -> None:
    console = console or Console()
    v = result.verdict
    base = (result.base or {}).get("name", "-")
    head = result.head.get("name", "-")
    c = result.counts
    title = Text(f" {v} ", style=f"bold white on {COLORS.get(v, 'white')}")
    body = Text()
    body.append(f"{result.suite}  ", style="bold")
    body.append(f"{base} -> {head}\n" if result.base else f"{head}\n")
    body.append(
        f"cases {c.get('total_cases', 0)}  pass {c.get('pass_cases', 0)}  warn {c.get('warn_cases', 0)}  fail {c.get('fail_cases', 0)}  "
        f"improved {c.get('improved_cases', 0)}  broken {c.get('broken_cases', 0)}  unstable {c.get('unstable_cases', 0)}"
    )
    console.print(Panel(body, title=title, title_align="left", border_style=COLORS.get(v, "white")))

    table = Table(title="metrics (mean [95% CI])", show_lines=False)
    table.add_column("metric")
    if result.base:
        table.add_column("base")
    table.add_column("head")
    if result.base:
        table.add_column("delta")
        table.add_column("p adj")
    for name, m in result.metrics.items():
        if name == "assertion_pass_rate":
            continue
        row = [name]
        if result.base:
            row.append(_ci(m.get("base")))
        row.append(_ci(m.get("head")))
        if result.base:
            d = m.get("delta", {})
            row.append(_ci(d))
            row.append(_fmt(d.get("p_adjusted"), 3))
        table.add_row(*row)
    ap = result.metrics.get("assertion_pass_rate", {})
    if ap:
        row = ["assertion pass rate"]
        if result.base:
            row.append(_fmt((ap.get("base") or {}).get("rate")))
        row.append(_fmt((ap.get("head") or {}).get("rate")))
        if result.base:
            row += ["", ""]
        table.add_row(*row)
    console.print(table)

    pw = result.pairwise
    if pw.get("n"):
        console.print(
            f"pairwise: head wins {pw['head_wins']}  base wins {pw['base_wins']}  ties {pw['ties']}  "
            f"position consistency {_fmt(pw.get('position_consistency'))}"
        )

    def show(status_set: set[str], label: str) -> None:
        rows = [r for r in result.cases if r["status"] in status_set]
        if not rows:
            return
        rows.sort(key=lambda r: r["delta"].get("score", 0.0))
        t = Table(title=label, show_lines=True)
        t.add_column("case", no_wrap=True)
        t.add_column("status")
        t.add_column("why")
        if result.base:
            t.add_column("base output")
        t.add_column("head output")
        for r in rows[:top]:
            head_out = r["head"]["trials"][0]["transcript"] if r["head"]["trials"] else {}
            failing = [a for tr in r["head"]["trials"][:1] for a in tr["assertions"] if not a["passed"]]
            why = "; ".join(r["reasons"] + [f"{a['label']}: {a['message']}" for a in failing])
            cells = [r["case"]["id"], Text(r["status"], style=COLORS.get(r["status"], "white")), _short(why, 120)]
            if result.base:
                base_out = r["base"]["trials"][0]["transcript"] if r["base"] and r["base"]["trials"] else {}
                cells.append(_short(base_out.get("raw_output") or str(base_out.get("error") or "")))
            cells.append(_short(head_out.get("raw_output") or str(head_out.get("error") or "")))
            t.add_row(*cells)
        console.print(t)

    show({"FAIL", "BROKEN"}, "regressions")
    show({"WARN", "UNSTABLE"}, "warnings")
    if result.base:
        show({"IMPROVED"}, "improvements")
    fired = [g for g in result.gate_trace if g["triggered"]]
    if fired:
        console.print("gates fired: " + escape(", ".join(f"[{g['level']}] {g['expr']}" for g in fired)))
    cost = result.cost.get("run_usd")
    if cost is not None:
        console.print(f"run cost: ${cost:.4f}")


def render_rank(rows: list[dict], console: Console | None = None) -> None:
    console = console or Console()
    t = Table(title="ranking")
    for col in ("rank", "candidate", "verdict", "score [95% CI]", "head win rate", "assertion failures", "tied with"):
        t.add_column(col)
    for r in rows:
        ci = "-" if r["mean"] is None else f"{r['mean']:.2f} [{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]"
        t.add_row(
            str(r["rank"]),
            r["name"],
            Text(r["verdict"] or "-", style=COLORS.get(r["verdict"], "white")),
            ci,
            _fmt(r["head_win_rate"]),
            str(r["assertion_failures"]),
            ", ".join(r["tied_with"]) or "-",
        )
    console.print(t)
