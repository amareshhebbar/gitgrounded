import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kit

REPO_ID = "AmareshHebbar/GitGrounded_Bench"


def tokens(data: dict) -> int:
    c = data.get("cost") or {}
    return sum((c.get(s) or {}).get("input_tokens", 0) + (c.get(s) or {}).get("output_tokens", 0) for s in ("base", "head"))


FIELDS = ("category", "priority", "policy_line")


def _first(side: dict) -> dict:
    trials = side.get("trials") or []
    return trials[0] if trials else {}


def _sig(trial: dict):
    tr = trial.get("transcript") or {}
    out = tr.get("output")
    ok = all(a.get("passed", True) for a in trial.get("assertions") or [])
    if not isinstance(out, dict):
        return (ok, None)
    return (ok, tuple(str(out.get(f, "")).strip().lower() for f in FIELDS))


def behavior_changes(data: dict) -> int:
    n = 0
    for c in data.get("cases") or []:
        b, h = _sig(_first(c.get("base") or {})), _sig(_first(c.get("head") or {}))
        if b != h:
            n += 1
    return n


def unparsed(data: dict) -> int:
    n = 0
    for c in data.get("cases") or []:
        for side in ("base", "head"):
            out = ((_first(c.get(side) or {}).get("transcript")) or {}).get("output")
            n += not isinstance(out, dict)
    return n


def compute(results: Path) -> dict:
    plan = {p["name"]: p for p in kit.read_jsonl(results / "scenarios.jsonl")}
    rows = []
    for name, p in plan.items():
        f = results / "runs" / f"{name}.json"
        if not f.exists():
            err = results / "runs" / f"{name}.error.json"
            rows.append({"name": name, "expect": p["expect"], "verdict": None,
                         "error": kit.read_json(err)["error"][-300:] if err.exists() else "not run"})
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        counts = d.get("counts") or {}
        rows.append({
            "name": name,
            "expect": p["expect"],
            "verdict": d.get("verdict"),
            "fail_cases": counts.get("fail_cases"),
            "warn_cases": counts.get("warn_cases"),
            "regressions": counts.get("regressions"),
            "seconds": (d.get("_bench") or {}).get("seconds"),
            "run_usd": (d.get("cost") or {}).get("run_usd"),
            "app_tokens": tokens(d),
            "changed_cases": behavior_changes(d),
            "unparsed_outputs": unparsed(d),
        })
    done = [r for r in rows if r["verdict"]]
    bad = [r for r in done if r["expect"] == "FAIL"]
    safe = [r for r in done if r["expect"] == "PASS" and r["name"].startswith("safe-")]
    nulls = [r for r in done if r["name"].startswith("null-")]

    def block(items, hit):
        k = sum(1 for r in items if hit(r["verdict"]))
        return {"n": len(items), "k": k, "rate": k / len(items) if items else None, "ci": kit.wilson(k, len(items))}

    effective = [r for r in bad if r.get("changed_cases", 0) > 0]
    inert = [r for r in bad if r.get("changed_cases", 0) == 0]
    secs = [r["seconds"] for r in done if r.get("seconds")]
    usd = [r["run_usd"] for r in done if isinstance(r.get("run_usd"), (int, float))]
    return {
        "rows": rows,
        "summary": {
            "caught_fail": block(bad, lambda v: v == "FAIL"),
            "caught_fail_or_warn": block(bad, lambda v: v in ("FAIL", "WARN")),
            "safe_false_fail": block(safe, lambda v: v == "FAIL"),
            "safe_false_fail_or_warn": block(safe, lambda v: v in ("FAIL", "WARN")),
            "null_false_fail_or_warn": block(nulls, lambda v: v in ("FAIL", "WARN")),
            "effective_breaking": len(effective),
            "inert_breaking": len(inert),
            "inert_names": [r["name"] for r in inert],
            "unparsed_outputs": sum(r.get("unparsed_outputs", 0) for r in done),
            "caught_effective_fail": block(effective, lambda v: v == "FAIL"),
            "caught_effective_fail_or_warn": block(effective, lambda v: v in ("FAIL", "WARN")),
            "not_run": sum(1 for r in rows if not r["verdict"]),
            "median_seconds": statistics.median(secs) if secs else None,
            "total_usd_reported": round(sum(usd), 4) if usd else None,
            "median_app_tokens": statistics.median([r["app_tokens"] for r in done]) if done else None,
        },
        "setup": kit.read_json(results / "setup.json") if (results / "setup.json").exists() else {},
    }


def ci(b) -> str:
    return f"95% CI {kit.pct(b['ci'][0], 0)} to {kit.pct(b['ci'][1], 0)}"


def headline(res: dict, root: str | None) -> str:
    s, st = res["summary"], res["setup"]
    L = ["# GitGrounded bench", ""]
    L.append("Can GitGrounded tell a breaking prompt or policy change from a harmless one on a real LLM app? "
             "Each scenario is one git branch of the triage example. GitGrounded runs it against the baseline with the same locked cases and returns PASS, WARN or FAIL.")
    L.append("")
    L.append(f"* Breaking changes caught as FAIL: **{s['caught_fail']['k']}/{s['caught_fail']['n']}** ({ci(s['caught_fail'])})")
    L.append(f"* Breaking changes caught as FAIL or WARN: **{s['caught_fail_or_warn']['k']}/{s['caught_fail_or_warn']['n']}** ({ci(s['caught_fail_or_warn'])})")
    L.append(f"* Breaking edits that really changed the app's output on at least one case: **{s['effective_breaking']}/{s['caught_fail']['n']}**. "
             f"Of those, caught as FAIL: **{s['caught_effective_fail']['k']}/{s['caught_effective_fail']['n']}** ({ci(s['caught_effective_fail'])}), "
             f"as FAIL or WARN: **{s['caught_effective_fail_or_warn']['k']}/{s['caught_effective_fail_or_warn']['n']}**")
    if s["inert_names"]:
        L.append(f"* Breaking edits the model ignored (same category, priority, policy line and assertion results on every case, so PASS is correct): {', '.join(s['inert_names'])}")
    L.append(f"* Harmless wording changes wrongly marked FAIL: **{s['safe_false_fail']['k']}/{s['safe_false_fail']['n']}** ({ci(s['safe_false_fail'])})")
    L.append(f"* Harmless wording changes marked FAIL or WARN: {s['safe_false_fail_or_warn']['k']}/{s['safe_false_fail_or_warn']['n']}")
    L.append(f"* Empty commits marked FAIL or WARN: {s['null_false_fail_or_warn']['k']}/{s['null_false_fail_or_warn']['n']}")
    if s["median_seconds"] is not None:
        L.append(f"* Median time per PR check: {s['median_seconds']:.0f} s")
    if s["total_usd_reported"]:
        L.append(f"* Total spend reported by GitGrounded: ${s['total_usd_reported']:.2f}")
    if s["not_run"]:
        L.append(f"* Scenarios that did not finish: {s['not_run']}")
    L.append(f"* App outputs that were not valid JSON objects, base and head together: {s.get('unparsed_outputs', 0)}")
    L.append("")
    if st:
        L.append(f"App model: `{st['app'].get('model')}`. Judge model: `{st['judge'].get('model')}`. Locked cases: {st.get('cases')}. Baseline commit `{st.get('baseline_commit', '')[:12]}`.")
        L.append("")
    L.append("A case counts as changed when its category, priority, policy line or assertion results differ between baseline and head. This check reads the raw transcripts and does not use GitGrounded's verdict.")
    L.append("")
    L.append("| scenario | expected | verdict | cases with changed output | fail cases | warn cases | seconds |")
    L.append("|---|---|---|---|---|---|---|")
    for r in res["rows"]:
        v = r["verdict"] or "not run"
        L.append(f"| {r['name']} | {r['expect']} | {v} | {r.get('changed_cases', '')} | {r.get('fail_cases', '')} | {r.get('warn_cases', '')} | {r.get('seconds', '')} |")
    L += [
        "",
        "Every branch diff is in `scenarios.jsonl`, and every full GitGrounded result, with each case transcript and judge reason, is in `runs/`.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "git clone https://github.com/amareshhebbar/gitgrounded && cd gitgrounded",
        "pip install -e \".[sign]\"",
        "cp bench/proof/.env.example bench/proof/.env",
        "bash bench/proof/run.sh",
        "```",
        "",
        "## Verify",
        "",
        "```bash",
        f"python -c \"from huggingface_hub import snapshot_download as s; s('{REPO_ID}', repo_type='dataset', local_dir='bench/proof/results')\"",
        "python bench/proof/verify.py",
        "```",
        "",
    ]
    if root:
        L.append(f"Manifest root: `{root}`")
        L.append("")
    return "\n".join(L)


def build(results: Path) -> str:
    res = compute(results)
    kit.write_json(results / "report" / "results.json", res)
    man = kit.build_manifest(results, ["runs"], {"repo_id": REPO_ID})
    for f in ("report/results.json", "scenarios.jsonl", "setup.json"):
        p = results / f
        if p.exists():
            man["files"].append({"path": f, "sha256": kit.sha256_file(p), "bytes": p.stat().st_size})
    man["root"] = kit.merkle_root([f["sha256"] for f in man["files"]])
    kit.write_json(results / "manifest.json", man)
    page = headline(res, man["root"])
    (results / "report" / "HEADLINE.md").write_text(page, encoding="utf-8")
    (results / "README.md").write_text(page, encoding="utf-8")
    return page


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "results"))
    print(build(Path(ap.parse_args().results)))


if __name__ == "__main__":
    main()
