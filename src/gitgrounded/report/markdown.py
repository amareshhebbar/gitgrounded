from gitgrounded.report.model import RunResult

MARKER = "<!-- gitgrounded-report -->"


def _f(v, d: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{d}f}"


def _one_line(text: str, n: int = 110) -> str:
    t = " ".join((text or "").split()).replace("|", "\\|")
    return t if len(t) <= n else t[: n - 3] + "..."


def render_markdown(
    result: RunResult, report_url: str | None = None, bundle_info: dict | None = None, top: int = 8
) -> str:
    c = result.counts
    base = (result.base or {}).get("name")
    head = result.head.get("name")
    lines = [MARKER, f"## GitGrounded: **{result.verdict}**", ""]
    lines.append(
        f"`{result.suite}` {('`' + base + '` -> ') if base else ''}`{head}` &middot; {c.get('total_cases', 0)} cases &middot; {result.trials} trial(s)"
    )
    lines.append("")
    lines.append(
        f"pass {c.get('pass_cases', 0)} &middot; fail {c.get('fail_cases', 0)} &middot; warn {c.get('warn_cases', 0)} &middot; "
        f"improved {c.get('improved_cases', 0)} &middot; broken in both {c.get('broken_cases', 0)} &middot; unstable {c.get('unstable_cases', 0)} &middot; "
        f"new assertion failures {c.get('new_assertion_failures', 0)}"
    )
    lines.append("")
    lines.append("| metric | base | head | delta [95% CI] | p adj |")
    lines.append("|---|---|---|---|---|")
    for name, m in result.metrics.items():
        if name == "assertion_pass_rate":
            continue
        d = m.get("delta") or {}
        delta = f"{_f(d.get('mean'))} [{_f(d.get('ci_lower'))}, {_f(d.get('ci_upper'))}]" if d else "n/a"
        lines.append(
            f"| {name} | {_f((m.get('base') or {}).get('mean'))} | {_f(m['head'].get('mean'))} | {delta} | {_f(d.get('p_adjusted'), 3)} |"
        )
    pw = result.pairwise
    if pw.get("n"):
        lines.append("")
        lines.append(
            f"Pairwise judge: head preferred {pw['head_wins']}x, base preferred {pw['base_wins']}x, ties {pw['ties']} (position consistency {_f(pw.get('position_consistency'))})."
        )
    fired = [g for g in result.gate_trace if g["triggered"]]
    if fired:
        lines.append("")
        lines.append("Gates fired: " + ", ".join(f"`{g['expr']}`" for g in fired))
    bad = [r for r in result.cases if r["status"] in ("FAIL", "BROKEN", "WARN")]
    if bad:
        bad.sort(key=lambda r: ({"FAIL": 0, "BROKEN": 1, "WARN": 2}[r["status"]], r["delta"].get("score", 0.0)))
        lines += [
            "",
            "<details><summary>Regressions and warnings</summary>",
            "",
            "| case | status | why | head output |",
            "|---|---|---|---|",
        ]
        for r in bad[:top]:
            ht = r["head"]["trials"][0]["transcript"] if r["head"]["trials"] else {}
            fails = [a for t in r["head"]["trials"][:1] for a in t["assertions"] if not a["passed"]]
            why = "; ".join(r["reasons"] + [f"{a['label']}: {a['message']}" for a in fails])
            lines.append(
                f"| `{r['case']['id']}` | {r['status']} | {_one_line(why, 90)} | {_one_line(ht.get('raw_output') or ht.get('error') or '')} |"
            )
        if len(bad) > top:
            lines.append(f"| ... | | {len(bad) - top} more | |")
        lines += ["", "</details>"]
    if result.coverage:
        s = result.coverage.get("summary", {})
        lines.append("")
        lines.append(
            f"Coverage: {s.get('behaviors_covered')}/{s.get('behaviors')} behaviors, mutation score {_f(s.get('mutation_score'))}."
        )
    if bundle_info:
        sig = bundle_info.get("signature", {})
        lines.append("")
        lines.append(
            f"Evidence: merkle root `{bundle_info.get('merkle_root', '')[:16]}`, signature `{sig.get('type', 'none')}`. Verify with `gitgrounded verify <bundle>.ggb`."
        )
    if report_url:
        lines.append(f"[Full report]({report_url})")
    lines.append("")
    lines.append(
        f"<sub>run {result.run_id} &middot; judge {result.providers.get('judge', {}).get('model')} &middot; cost ${_f(result.cost.get('run_usd'), 4)}</sub>"
    )
    return "\n".join(lines) + "\n"
