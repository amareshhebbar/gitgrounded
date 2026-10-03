import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from gitgrounded import __version__
from gitgrounded.errors import GitGroundedError

console = Console(stderr=False)
err = Console(stderr=True)

REMOVED_FLAGS = {
    "--old": "gitgrounded run --base <ref> --head <ref>",
    "--new": "gitgrounded run --base <ref> --head <ref>",
    "--demo": "python examples/triage/make_demo_repo.py <dir>",
    "--compare": "gitgrounded check --url <url> --label <name>",
    "--check": "gitgrounded check <target>",
    "--labels": "gitgrounded history list",
    "--del-v": "gitgrounded history delete <label> --version <n>",
    "--del-v-all": "gitgrounded history delete --all",
    "--rank": "gitgrounded rank --base <ref> <candidates...>",
    "--app-module": "a python or framework target in gitgrounded.yml",
    "--gitgrounded-yml": "--config <file>",
    "--seed-cases": "gitgrounded suite import <file>",
}


def reject_removed(argv: list[str]) -> None:
    if not argv or not argv[0].startswith("--") or argv[0] in ("-h", "--help", "--version"):
        return
    hits = [a for a in argv if a in REMOVED_FLAGS]
    if hits:
        lines = [f"{h} was removed in 0.2; use: {REMOVED_FLAGS[h]}" for h in dict.fromkeys(hits)]
        raise SystemExit("\n".join(lines))


def _engine(args):
    from gitgrounded.config.loader import load_config
    from gitgrounded.engine import Engine
    from gitgrounded.project import find_project

    project = find_project(config=getattr(args, "config", None))
    cfg = load_config(project.config_path)
    if getattr(args, "budget_usd", None) is not None:
        cfg.execution.budget_usd = args.budget_usd
    if getattr(args, "concurrency", None):
        cfg.execution.max_concurrency = args.concurrency
    if project.config_path is None and getattr(args, "command", "") not in ("check",):
        err.print("[yellow]no gitgrounded.yml found; run `gitgrounded init`[/yellow]")
    verbose = getattr(args, "verbose", False)
    log = (lambda m: err.print(f"[dim]{m}[/dim]")) if verbose or sys.stderr.isatty() else (lambda m: None)
    return Engine(project, cfg, log=log)


def _attach_coverage(engine, result) -> None:
    from gitgrounded.coverage.suite_store import SuiteStore

    _, suite = engine.cfg.suite(result.suite) if result.suite in engine.cfg.suites else (None, None)
    if suite is None or suite.cases:
        return
    cov = SuiteStore(engine.project, result.suite).read_json("coverage.json")
    if cov:
        result.coverage = {"summary": cov.get("summary", {})}


def _outputs(args, engine, result) -> dict:
    from gitgrounded.report.html import render_html
    from gitgrounded.report.junit import render_junit
    from gitgrounded.report.markdown import render_markdown
    from gitgrounded.report.terminal import render_run

    run_dir = engine.project.runs_dir / result.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    bundle_info = None
    if getattr(args, "bundle", None) is not None:
        bundle_info = _write_bundle(
            engine,
            result,
            Path(args.bundle) if args.bundle != "auto" else run_dir / "evidence.ggb",
            getattr(args, "sign", None),
        )
    html_path = Path(args.html) if getattr(args, "html", None) else run_dir / "report.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(result, (bundle_info or {}).get("provenance")), encoding="utf-8")
    md = render_markdown(result, bundle_info=bundle_info)
    (run_dir / "summary.md").write_text(md, encoding="utf-8")
    if getattr(args, "markdown", None):
        Path(args.markdown).write_text(md, encoding="utf-8")
    if getattr(args, "junit", None):
        Path(args.junit).write_text(render_junit(result), encoding="utf-8")
    if getattr(args, "json_out", None):
        Path(args.json_out).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    fmt = getattr(args, "format", "terminal")
    if fmt == "json":
        print(json.dumps(result.summary(), indent=2, default=str))
    elif fmt == "markdown":
        print(md)
    else:
        render_run(result, console)
        console.print(f"[dim]report: {html_path}[/dim]")
        if bundle_info:
            console.print(
                f"[dim]evidence bundle: {bundle_info['path']} (signature: {bundle_info['signature'].get('type')})[/dim]"
            )
    if getattr(args, "open", False):
        webbrowser.open(html_path.resolve().as_uri())
    return {"html": str(html_path), "bundle": bundle_info}


def _write_bundle(engine, result, path: Path, sign: str | None) -> dict:
    from gitgrounded.coverage.suite_store import SuiteStore
    from gitgrounded.evidence.bundle import build_bundle
    from gitgrounded.evidence.sign import build_signer
    from gitgrounded.report.html import render_html

    store = SuiteStore(engine.project, result.suite)
    suite_files = {}
    for name in ("current.jsonl", "coverage.json", "mutation.json", "behavior_map.json", "suite.json"):
        p = store.path(name)
        if p.exists():
            suite_files[name] = p.read_bytes()
    signer = build_signer(sign or engine.cfg.evidence.sign)
    captured = {}

    def html_fn(res, provenance):
        captured.update(provenance)
        return render_html(res, provenance)

    info = build_bundle(
        result,
        path,
        engine.cfg.model_dump(mode="json"),
        suite_files,
        html_fn,
        engine.cfg.evidence.redact,
        engine.cfg.evidence.include_transcripts,
        signer,
    )
    info["provenance"] = captured
    result.evidence = (result.evidence or {}) | {
        "bundle": info["path"],
        "merkle_root": info["merkle_root"],
        "signature": info["signature"],
    }
    return info


def _exit_code(verdict: str, fail_on: str) -> int:
    if fail_on == "never":
        return 0
    if fail_on == "warn":
        return 1 if verdict in ("FAIL", "WARN") else 0
    return 1 if verdict == "FAIL" else 0


def _run_opts(args):
    from gitgrounded.engine import RunOptions

    return RunOptions(
        trials=args.trials,
        quick=args.quick,
        max_cases=args.max_cases,
        generate=False if args.no_generate else None,
        case_ids=args.case.split(",") if getattr(args, "case", None) else None,
    )


def cmd_run(args) -> int:
    engine = _engine(args)
    try:
        opts = _run_opts(args)
        if args.minimal:
            from gitgrounded.coverage.suite_store import SuiteStore

            suite_name, _ = engine.cfg.suite(args.suite)
            cases = SuiteStore(engine.project, suite_name).cases(minimal=True)
            from gitgrounded.sources.variant import diff_text, materialize

            _, suite = engine.cfg.suite(suite_name)
            watch = engine.watch_paths(suite)
            base = materialize(engine.project, args.base, watch)
            head = materialize(engine.project, args.head, watch)
            result = engine.run_variants(
                suite_name, base, head, diff_text(engine.project, base, head, watch), opts, cases=cases or None
            )
        else:
            result = engine.run_git(args.suite, args.base, args.head, opts)
        _attach_coverage(engine, result)
        engine.write_result(result)
        _outputs(args, engine, result)
        code = _exit_code(result.verdict, args.fail_on)
        if args.certify:
            suite_name, _ = engine.cfg.suite(args.suite)
            from gitgrounded.coverage.suite_store import SuiteStore

            cases = SuiteStore(engine.project, suite_name).cases()
            score = result.metrics.get("score") or {}
            head_score = score.get("head") or {}
            delta = score.get("delta") or {}
            row = {
                "rank": 1,
                "candidate": result.head.get("name"),
                "prompt": "",
                "model": "",
                "score_mean": head_score.get("mean"),
                "ci_lower": head_score.get("ci_lower"),
                "ci_upper": head_score.get("ci_upper"),
                "assertion_pass_rate": ((result.metrics.get("assertion_pass_rate") or {}).get("head") or {}).get(
                    "rate"
                ),
                "cost_usd": (result.cost.get("head") or {}).get("usd"),
                "p50_ms": (result.latency.get("head") or {}).get("p50_ms"),
                "verdict_vs_baseline": result.verdict,
                "delta": delta.get("mean"),
                "p_adjusted": delta.get("p_adjusted"),
                "win_rate": result.pairwise.get("head_win_rate"),
                "loss_rate": result.pairwise.get("base_win_rate"),
            }
            code = max(
                code,
                _certify(
                    args, engine, suite_name, cases, [(str(result.head.get("name")), result)], [row], "regression"
                ),
            )
        return code
    finally:
        engine.close()


def _certify(args, engine, suite_name, cases, pairs, rows, kind) -> int:
    from gitgrounded.evidence.certify import certify

    out = (
        Path(args.out)
        if getattr(args, "out", None)
        else engine.project.state_dir / "certificates" / f"{suite_name}-{pairs[0][1].run_id}.ggb"
    )
    info = certify(engine, suite_name, cases, pairs, rows, out, getattr(args, "sign", None), kind)
    t = info["traps"]
    color = "green" if info["certified"] else "red"
    console.print(
        f"[bold {color}]{'CERTIFIED' if info['certified'] else 'NOT CERTIFIED'}[/bold {color}]  judge traps {t['correct']}/{t['total']}  signature {info['signature'].get('type')}"
    )
    for r in info["reasons"]:
        console.print(f"[red]  {escape(r)}[/red]")
    console.print(f"[dim]certificate: {info['path']}\npage: {info['html']}[/dim]")
    if info.get("pdf"):
        console.print(f"[dim]pdf: {info['pdf']}[/dim]")
    if getattr(args, "open", False):
        webbrowser.open(Path(info["html"]).resolve().as_uri())
    return 0 if info["certified"] else 1


def cmd_compare(args) -> int:
    from gitgrounded.compare import run_compare

    engine = _engine(args)
    try:
        res = run_compare(
            engine,
            args.prompt,
            args.model or [],
            context=args.context or [],
            baseline=args.baseline,
            budget=8 if args.quick else args.budget_cases,
            min_per=1 if args.quick else 2,
            regenerate=args.regenerate,
            quick=args.quick,
            trials=args.trials or 1,
            json_mode=args.json_mode,
            template=args.suite,
            log=lambda m: err.print(f"[dim]{m}[/dim]"),
        )
        return _leaderboard_out(args, engine, res)
    finally:
        engine.close()


def _leaderboard_out(args, engine, res) -> int:
    from rich.table import Table

    from gitgrounded.evidence.certify import render_certificate_html

    if args.format == "json":
        print(
            json.dumps(
                {
                    "suite": res.suite,
                    "cases": len(res.cases),
                    "baseline": res.baseline,
                    "leaderboard": res.leaderboard,
                },
                indent=2,
                default=str,
            )
        )
    else:
        t = Table(
            title=f"leaderboard  ({len(res.cases)} locked questions, suite {res.suite} {res.suite_version or ''})"
        )
        for col in (
            "rank",
            "candidate",
            "score [95% CI]",
            "code checks",
            "vs baseline",
            "wins/losses",
            "cost",
            "p50",
        ):
            t.add_column(col)
        for r in res.leaderboard:
            ci = "-" if r["score_mean"] is None else f"{r['score_mean']:.2f} [{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]"
            wl = "-" if r["win_rate"] is None else f"{r['win_rate']:.0%}/{r['loss_rate']:.0%}"
            vs = (r["verdict_vs_baseline"] or "-") + ("" if r["delta"] is None else f" {r['delta']:+.2f}")
            t.add_row(
                str(r["rank"]),
                r["candidate"],
                ci,
                _pct(r["assertion_pass_rate"]),
                vs,
                wl,
                f"${(r['cost_usd'] or 0):.4f}",
                f"{(r['p50_ms'] or 0):.0f}ms",
            )
        console.print(t)
    page = engine.project.state_dir / "compare" / f"{res.suite}-latest.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    if not args.certify:
        preview = {
            "kind": getattr(args, "kind", "comparison"),
            "id": "preview",
            "certified": False,
            "project": engine.cfg.project.name,
            "created_at": res.results[0][1].created_at if res.results else "",
            "tool_version": __version__,
            "reasons": ["preview only; rerun with --certify to produce a signed certificate"],
            "leaderboard": res.leaderboard,
            "pairs": [],
            "suite": {
                "name": res.suite,
                "version": res.suite_version,
                "cases": len(res.cases),
                "behaviors": None,
                "generator": engine.cfg.providers.generator.model,
                "integrity": "",
                "dataset_hash": "",
            },
            "judge": engine.cfg.providers.judge.model_dump(),
            "panel": [],
            "offline": False,
            "traps": {"total": 0, "correct": 0, "accuracy": 0, "threshold": 0, "passed": False},
            "calibration": None,
            "coverage": None,
        }
        page.write_text(render_certificate_html(preview), encoding="utf-8")
        console.print(f"[dim]leaderboard page: {page}[/dim]")
        if args.open:
            webbrowser.open(page.resolve().as_uri())
        return 0
    return _certify(
        args, engine, res.suite, res.cases, res.results, res.leaderboard, getattr(args, "kind", "comparison")
    )


def cmd_benchmark(args) -> int:
    from gitgrounded.compare import run_benchmark

    engine = _engine(args)
    try:
        res = run_benchmark(
            engine,
            args.target or [],
            args.spec or [],
            context=args.context or [],
            baseline=args.baseline,
            budget=8 if args.quick else args.budget_cases,
            min_per=1 if args.quick else 2,
            regenerate=args.regenerate,
            quick=args.quick,
            trials=args.trials or 1,
            template=args.suite,
            log=lambda m: err.print(f"[dim]{m}[/dim]"),
        )
        args.kind = "benchmark"
        return _leaderboard_out(args, engine, res)
    finally:
        engine.close()


def cmd_doctor(args) -> int:
    from rich.table import Table

    from gitgrounded.config.schema import ProviderCfg
    from gitgrounded.providers import env
    from gitgrounded.providers.base import build_provider, is_offline

    engine = _engine(args)
    try:
        t = Table(title="providers")
        for col in ("provider", "api key", "base url", "default model", "key variables"):
            t.add_column(col)
        for r in env.status():
            t.add_row(r["provider"], r["key"], r["base_url"] or "-", r["default_model"], ", ".join(r["env"]) or "-")
        console.print(t)
        roles = Table(title="roles")
        for col in ("role", "provider", "model", "temperature", "ping"):
            roles.add_column(col)
        entries = [
            ("judge", engine.cfg.providers.judge),
            ("generator", engine.cfg.providers.generator),
            ("validator", engine.cfg.providers.validator or engine.cfg.providers.judge),
        ]
        entries += [(f"panel {i + 1}", p) for i, p in enumerate(engine.cfg.providers.panel)]
        entries += [(f"target {i + 1}", ProviderCfg(**m)) for i, m in enumerate(env.target_models())]
        code = 0
        for role, cfg in entries:
            ping = "-"
            if args.ping:
                try:
                    comp = build_provider(cfg).complete(
                        "", [{"role": "user", "content": "Reply with the word ok."}], task="ping"
                    )
                    ping = f"ok {comp.latency_ms:.0f}ms"
                except Exception as e:
                    ping = f"FAIL {str(e)[:60]}"
                    code = 1
            roles.add_row(role, cfg.provider, cfg.model, str(cfg.temperature), escape(ping))
        console.print(roles)
        console.print(f"offline mode: {'ON (all calls use the mock provider)' if is_offline() else 'off'}")
        return code
    finally:
        engine.close()


def cmd_check(args) -> int:
    from gitgrounded.cases.loader import load_cases
    from gitgrounded.config.schema import HttpTarget, SuiteCfg

    engine = _engine(args)
    try:
        cases = load_cases(Path(args.cases)) if args.cases else None
        opts = _run_opts(args)
        results = []
        if args.url:
            name = "adhoc_http"
            engine.cfg.targets[name] = HttpTarget(type="http", url=args.url, output=args.output)
            suite_name = f"check:{args.label or args.url}"
            engine.cfg.suites[suite_name] = SuiteCfg(
                target=name, judges=[{"type": "rubric"}, {"type": "pairwise"}], generate={"enabled": False}
            )
            if cases is None:
                raise GitGroundedError('--url needs --cases FILE (JSONL or JSON list of {"input": ...})')
            results.append(engine.run_check(suite_name, args.label or args.url, opts, cases=cases))
        else:
            suites = (
                [args.suite]
                if args.suite
                else [n for n, s in engine.cfg.suites.items() if engine.cfg.target(s.target).type == "http"]
            )
            if args.target:
                suites = [n for n in suites if engine.cfg.suites[n].target == args.target]
            if not suites:
                raise GitGroundedError("no http suites found; add a suite whose target has type: http, or use --url")
            for name in suites:
                label = args.label or engine.cfg.suites[name].target
                results.append(engine.run_check(name, label, opts, cases=cases))
        code = 0
        for result in results:
            _outputs(args, engine, result)
            if result.base is None:
                console.print(
                    f"[dim]stored baseline v{result.head.get('version')} for '{result.head.get('label')}'; the next check compares against it[/dim]"
                )
            code = max(code, _exit_code(result.verdict, args.fail_on))
        return code
    finally:
        engine.close()


def cmd_rank(args) -> int:
    from gitgrounded.report.terminal import render_rank
    from gitgrounded.stats.ranking import rank_results

    engine = _engine(args)
    try:
        opts = _run_opts(args)
        summaries = []
        for cand in args.candidates:
            result = engine.run_git(args.suite, args.base, cand, opts)
            engine.write_result(result)
            summaries.append((cand, result.summary()))
            console.print(f"{cand}: {result.verdict}")
        rows = rank_results(summaries)
        if args.format == "json":
            print(json.dumps(rows, indent=2))
        else:
            render_rank(rows, console)
        return 1 if args.fail_on != "never" and all(r["verdict"] == "FAIL" for r in rows) else 0
    finally:
        engine.close()


def cmd_history(args) -> int:
    from gitgrounded.config.loader import load_config
    from gitgrounded.project import find_project
    from gitgrounded.store.history import History

    project = find_project(config=args.config)
    cfg = load_config(project.config_path)
    history = History(project.with_state_dir(cfg.project.state_dir).history_dir)
    if args.label == "list" or args.label is None:
        rows = history.labels()
        if not rows:
            console.print("no stored history yet")
        for name, latest in rows:
            console.print(f"{name:40s} latest v{latest}")
        return 0
    if args.label == "import":
        src = Path(args.target or ".versions")
        if not src.is_dir():
            raise GitGroundedError(f"{src} not found; pass the old .versions folder")
        from gitgrounded.cases.model import Case

        imported = 0
        for label_dir in sorted(p for p in src.iterdir() if p.is_dir()):
            for vfile in sorted(
                label_dir.glob("v*.json"), key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0
            ):
                data = json.loads(vfile.read_text(encoding="utf-8"))
                cases, trs = [], []
                for i, a in enumerate(data.get("answers", [])):
                    cid = f"legacy-{i + 1:03d}"
                    cases.append(Case(id=cid, input=a["input"]).model_dump(mode="json"))
                    out = a.get("parsed") if a.get("parsed") is not None else a.get("raw")
                    trs.append(
                        {
                            "case_id": cid,
                            "variant": "live",
                            "trial": 0,
                            "request": {},
                            "raw_output": a.get("raw") or "",
                            "output": out,
                        }
                    )
                history.save(
                    label_dir.name,
                    {"target": label_dir.name, "imported_from": str(vfile), "cases": cases, "transcripts": trs},
                )
                imported += 1
        console.print(f"imported {imported} version(s) from {src}")
        return 0
    if args.label == "delete":
        if args.all:
            console.print(f"deleted {history.delete_all()} label(s)")
            return 0
        if not args.target:
            raise GitGroundedError("history delete LABEL [--version N] or history delete --all")
        n = history.delete(args.target, args.version)
        console.print(f"deleted {n} version(s) of '{args.target}'")
        return 0
    versions = history.versions(args.label)
    if not versions:
        raise GitGroundedError(f"no history for '{args.label}'")
    for v in versions:
        snap = history.load(args.label, v)
        console.print(
            f"v{v}  {snap.get('saved_at', '')}  verdict vs previous: {snap.get('verdict', 'baseline')}  cases {len(snap.get('cases', []))}"
        )
    if args.rank:
        best = None
        for v in versions:
            snap = history.load(args.label, v)
            if snap.get("verdict") in ("PASS", None) or v == versions[0]:
                best = v
        console.print(f"latest version that did not regress: v{best}")
    return 0


def _pipeline(args, engine):
    from gitgrounded.coverage.pipeline import CoveragePipeline

    return CoveragePipeline(engine, args.suite, log=lambda m: err.print(f"[dim]{m}[/dim]"))


def cmd_discover(args) -> int:
    from rich.table import Table

    engine = _engine(args)
    try:
        found = _pipeline(args, engine).discover()
        if args.format == "json":
            print(
                json.dumps(
                    {"behaviors": [b.model_dump() for b in found["behaviors"]], "dimensions": found["dimensions"]},
                    indent=2,
                )
            )
            return 0
        t = Table(title=f"{len(found['behaviors'])} behaviors from {len(found['sentences'])} source sentences")
        for col in ("id", "kind", "severity", "statement", "source"):
            t.add_column(col)
        for b in found["behaviors"]:
            t.add_row(
                b.id, b.kind, b.severity, b.statement[:110], "implicit" if b.implicit else ", ".join(b.source_ids)[:40]
            )
        console.print(t)
        console.print("dimensions: " + "; ".join(f"{k}={len(v)}" for k, v in found["dimensions"].items()))
        if found.get("proposed_dimensions"):
            console.print(
                "proposed app specific dimensions (set coverage.apply_proposed_dimensions: true to use): "
                + "; ".join(f"{k}={v}" for k, v in found["proposed_dimensions"].items())
            )
        return 0
    finally:
        engine.close()


def cmd_synth(args) -> int:
    engine = _engine(args)
    try:
        out = _pipeline(args, engine).synth(incremental=not args.full, use_logs=not args.no_logs)
        if args.format == "json":
            print(json.dumps(out, indent=2))
        else:
            s = out["coverage"]
            console.print(
                f"[bold]suite v{out['version']}[/bold]: {out['cases']} cases for {out['behaviors']} behaviors ({out['dropped']} dropped by validation)"
            )
            console.print(
                f"behavior coverage {s['behaviors_covered']}/{s['behaviors']}, condition coverage {_pct(s['tuple_coverage'])}"
            )
            console.print(f"written to {out['path']}")
            console.print(
                "next: `gitgrounded suite review` to approve cases, `gitgrounded mutate` to measure suite strength"
            )
        return 0
    finally:
        engine.close()


def _pct(v) -> str:
    return "n/a" if v is None else f"{100 * v:.0f}%"


def cmd_mutate(args) -> int:
    engine = _engine(args)
    try:
        out = _pipeline(args, engine).mutate(ref=args.ref, repair=not args.no_repair, max_mutants=args.max_mutants)
        if args.format == "json":
            print(json.dumps(out, indent=2))
        else:
            for m in out["mutants"]:
                state = "[green]detected[/green]" if m["killed"] else "[red]survived[/red]"
                console.print(f"{m['id']:34s} {state}  {m['description'][:80]}")
            console.print(
                f"[bold]mutation score {_pct(out['score'])}[/bold] ({out['killed']}/{out['total']}), target {_pct(out['target'])}; minimal CI suite {out['minimal_cases']} cases"
            )
        return 0 if out["meets_target"] or args.fail_on == "never" else 1
    finally:
        engine.close()


def cmd_suite(args) -> int:
    from gitgrounded.coverage.suite_store import SuiteStore

    engine = _engine(args)
    try:
        suite_name, suite = engine.cfg.suite(args.suite)
        store = SuiteStore(engine.project, suite_name)
        if args.action == "review":
            from gitgrounded.coverage.review_server import serve

            if not store.exists():
                raise GitGroundedError(f"no synthesized suite '{suite_name}' yet; run `gitgrounded synth`")
            serve(store, args.port, open_browser=not args.no_browser, only_unreviewed=not args.all)
            return 0
        if args.action == "coverage":
            from gitgrounded.report.html import render_coverage_html

            cov = store.read_json("coverage.json")
            if not cov:
                raise GitGroundedError(f"no coverage data for '{suite_name}'; run `gitgrounded synth`")
            if args.format == "json":
                print(json.dumps(cov, indent=2))
                return 0
            out = Path(args.html) if args.html else store.path("coverage.html")
            out.write_text(
                render_coverage_html(
                    suite_name,
                    store.meta(),
                    cov,
                    store.read_json("mutation.json"),
                    store.read_json("dimensions.json", {}),
                    store.read_json("logs.json"),
                ),
                encoding="utf-8",
            )
            s = cov["summary"]
            console.print(
                f"behaviors {s['behaviors_covered']}/{s['behaviors']}  conditions {_pct(s['tuple_coverage'])}  mutation {_pct(s['mutation_score'])}  reviewed {_pct(s['reviewed_fraction'])}"
            )
            console.print(f"[dim]coverage report: {out}[/dim]")
            if args.open:
                webbrowser.open(out.resolve().as_uri())
            return 0
        if args.action == "show":
            meta = store.meta()
            console.print_json(json.dumps(meta))
            return 0
        if args.action == "import":
            from gitgrounded.cases.loader import load_cases, write_cases

            if not args.file:
                raise GitGroundedError("suite import needs --file")
            cases = load_cases(Path(args.file))
            dest = Path(args.out) if args.out else engine.project.resolve(suite.cases or f"{suite_name}.cases.jsonl")
            write_cases(dest, cases)
            console.print(f"wrote {len(cases)} cases to {dest}")
            return 0
        return 2
    finally:
        engine.close()


def _load_result(path: Path):
    from gitgrounded.evidence.verify import read_bundle
    from gitgrounded.report.model import RunResult

    if path.suffix == ".ggb":
        files = read_bundle(path)
        raise GitGroundedError(
            f"{path} is an evidence bundle; open report.html inside it or run `gitgrounded verify` ({len(files)} files)"
        )
    if path.is_dir():
        path = path / "result.json"
    return RunResult.model_validate_json(path.read_text(encoding="utf-8"))


def _resolve_result_path(args, engine) -> Path:
    if args.result and args.result != "latest":
        return Path(args.result)
    p = engine.latest_result_path()
    if p is None:
        raise GitGroundedError("no runs yet; run `gitgrounded run` first")
    return p


def cmd_report(args) -> int:
    from gitgrounded.report.html import render_html
    from gitgrounded.report.junit import render_junit
    from gitgrounded.report.markdown import render_markdown
    from gitgrounded.report.terminal import render_run

    engine = _engine(args)
    try:
        result = _load_result(_resolve_result_path(args, engine))
        if args.format == "html":
            out = Path(args.out) if args.out else engine.project.runs_dir / result.run_id / "report.html"
            out.write_text(render_html(result), encoding="utf-8")
            console.print(str(out))
            if args.open:
                webbrowser.open(out.resolve().as_uri())
        elif args.format == "markdown":
            text = render_markdown(result)
            Path(args.out).write_text(text, encoding="utf-8") if args.out else print(text)
        elif args.format == "junit":
            text = render_junit(result)
            Path(args.out).write_text(text, encoding="utf-8") if args.out else print(text)
        elif args.format == "json":
            print(result.model_dump_json(indent=2))
        else:
            render_run(result, console)
        return 0
    finally:
        engine.close()


def cmd_bundle(args) -> int:
    engine = _engine(args)
    try:
        result = _load_result(_resolve_result_path(args, engine))
        out = Path(args.out) if args.out else engine.project.runs_dir / result.run_id / "evidence.ggb"
        info = _write_bundle(engine, result, out, args.sign)
        console.print(
            f"bundle {info['path']}  merkle {info['merkle_root'][:16]}  signature {info['signature'].get('type')}"
        )
        return 0
    finally:
        engine.close()


def _tokens() -> set[str]:

    return {t.strip() for t in os.environ.get("GITGROUNDED_CERTIFIER_TOKENS", "").split(",") if t.strip()}


def cmd_certifier(args) -> int:
    from gitgrounded.certifier.service import CertifierService, serve

    if args.action == "pubkey":
        from gitgrounded.evidence.sign import LocalSigner

        key = Path(args.key) if args.key else Path(args.home) / "certifier_ed25519.pem"
        print(json.dumps({"name": args.name, **LocalSigner(key).public_key()}, indent=2))
        return 0
    svc = CertifierService(
        Path(args.home),
        _tokens(),
        Path(args.key) if args.key else None,
        name=args.name,
        allow_private=args.allow_private,
        max_cases=args.max_cases,
        public_url=args.public_url,
    )
    httpd = serve(svc, args.host, args.port)
    console.print(f"certifier {svc.name} on http://{args.host}:{httpd.server_address[1]}  key {svc.pub['key_id']}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        svc.close()
    return 0


def cmd_certify_remote(args) -> int:

    from gitgrounded.certifier.client import CertifierClient
    from gitgrounded.config.loader import load_config
    from gitgrounded.evidence.verify import verify_bundle
    from gitgrounded.project import find_project

    project = find_project(config=args.config)
    cfg = load_config(project.config_path)
    tcfg = cfg.target(args.target)
    target = tcfg.model_dump(mode="json", exclude_defaults=False)
    for k in ("watch",):
        target.pop(k, None)
    spec = "\n\n".join(project.resolve(s).read_text(encoding="utf-8") for s in args.spec or [])
    context = [project.resolve(c).read_text(encoding="utf-8") for c in args.context or []]
    client = CertifierClient(args.service, args.token or os.environ.get("GITGROUNDED_CERTIFIER_TOKEN"))
    pub = client.pubkey()
    if args.expect_key and args.expect_key not in (pub["key_id"], pub["public_key"]):
        raise GitGroundedError(f"service key {pub['key_id']} does not match --expect-key")
    job = client.submit(target, spec, context, args.budget_cases, args.name or cfg.project.name)
    console.print(f"job {job['id']} queued at {args.service}")
    job = client.wait(job["id"], timeout_s=args.timeout, log=lambda s: err.print(f"[dim]{s}[/dim]"))
    if job["status"] != "done":
        raise GitGroundedError(f"certification failed: {job.get('error')}")
    out = Path(args.out or f"{job['certificate_id']}.ggb")
    client.download(job["certificate_id"], out)
    if job.get("has_pdf"):
        client.download(job["certificate_id"], out.with_suffix(".pdf"), "pdf")
    res = verify_bundle(out, public_key=args.expect_key or pub["key_id"])
    color = "green" if job["certified"] else "red"
    console.print(
        f"[bold {color}]{'CERTIFIED' if job['certified'] else 'NOT CERTIFIED'}[/bold {color}] by {pub['name']} ({pub['key_id']})"
    )
    for r in job.get("reasons") or []:
        console.print(f"[red]  {escape(r)}[/red]")
    console.print(f"verify: {res.status}\ncertificate: {out}")
    return 0 if res.status == "VERIFIED_INDEPENDENT" and job["certified"] else 1


def cmd_verify(args) -> int:
    from rich.table import Table

    from gitgrounded.evidence.verify import verify_bundle

    res = verify_bundle(Path(args.bundle), identity=args.identity, issuer=args.issuer, public_key=args.public_key)
    if args.format == "json":
        print(json.dumps(res.to_dict(), indent=2))
    else:
        colors = {
            "VERIFIED": "green",
            "VERIFIED_SELF_SIGNED": "green",
            "VERIFIED_INDEPENDENT": "green",
            "VERIFIED_INTEGRITY_SIGNATURE_PRESENT": "green",
            "VERIFIED_UNSIGNED": "yellow",
        }
        m = res.manifest
        console.print(f"[bold {colors.get(res.status, 'red')}]{res.status}[/bold {colors.get(res.status, 'red')}]")
        if m:
            console.print(
                f"run {m.get('run_id')}  {m.get('project')}/{m.get('suite')}  verdict {m.get('verdict')}  created {m.get('created_at')}"
            )
            if m.get("head"):
                console.print(
                    f"head {m['head'].get('name')} {(m['head'].get('sha') or '')[:12]}  base {(m.get('base') or {}).get('name')} {((m.get('base') or {}).get('sha') or '')[:12]}"
                )
        if res.signature:
            console.print(f"signature: {res.signature}")
        bad = [c for c in res.checks if not c["ok"]]
        if bad or args.verbose:
            t = Table()
            t.add_column("check")
            t.add_column("ok")
            t.add_column("detail")
            for c in res.checks if args.verbose else bad:
                t.add_row(c["check"], "yes" if c["ok"] else "NO", c["detail"])
            console.print(t)
    return 0 if res.status.startswith("VERIFIED") else 1


def cmd_calibrate(args) -> int:
    from gitgrounded.judges.calibrate import calibrate

    engine = _engine(args)
    try:
        out = calibrate(
            Path(args.labels),
            args.rubric,
            engine.cfg.providers.judge,
            engine.cache,
            engine.project.root,
            args.threshold,
        )
        path = engine.project.state_dir / "calibration.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        if args.format == "json":
            print(json.dumps(out, indent=2))
        else:
            console.print(
                f"labels {out['labels']}  spearman {out['spearman']}  kappa(pass) {out['cohen_kappa_pass']}  agreement {out['pass_agreement']}"
            )
            console.print(f"[dim]saved {path}[/dim]")
        return 0
    finally:
        engine.close()


def cmd_mcp(args) -> int:
    if args.action == "serve":
        from gitgrounded.mcp.server import main as serve_main

        serve_main(args.project_dir)
        return 0
    from gitgrounded.mcp.introspect import McpClient, load_tools_file
    from gitgrounded.mcp.schema_diff import diff_tools

    if args.old_file and args.new_file:
        old_tools, new_tools = load_tools_file(Path(args.old_file)), load_tools_file(Path(args.new_file))
    else:
        from gitgrounded.sources.variant import materialize

        engine = _engine(args)
        try:
            tname = args.target or next((n for n, t in engine.cfg.targets.items() if t.type == "mcp"), None)
            if tname is None:
                raise GitGroundedError("no mcp target configured; pass --target or --old-file/--new-file")
            tcfg = engine.cfg.target(tname)
            watch = list(tcfg.watch) + ([tcfg.tools_file] if tcfg.tools_file else [])
            lists = []
            for ref in (args.base, args.head):
                v = materialize(engine.project, ref, watch)
                if tcfg.tools_file:
                    lists.append(load_tools_file(v.root / tcfg.tools_file))
                else:
                    lists.append(
                        McpClient(tcfg.transport, tcfg.command, tcfg.url, v.root, tcfg.env, tcfg.timeout_s).list_tools()
                    )
            old_tools, new_tools = lists
        finally:
            engine.close()
    out = diff_tools(old_tools, new_tools, desc_threshold=args.threshold)
    if args.format == "json":
        print(json.dumps(out, indent=2))
    else:
        colors = {"breaking": "red", "risky": "yellow", "safe": "green"}
        for c in out["changes"]:
            console.print(f"[{colors[c['level']]}]{c['level']:8s}[/{colors[c['level']]}] {c['tool']}: {c['detail']}")
        s = out["summary"]
        console.print(
            f"[bold]{s['breaking']} breaking, {s['risky']} risky, {s['safe']} safe -> suggested semver bump: {s['semver']}[/bold]"
        )
    if args.fail_on == "breaking" and out["summary"]["breaking"]:
        return 1
    if args.fail_on == "risky" and (out["summary"]["breaking"] or out["summary"]["risky"]):
        return 1
    return 0


def cmd_cache(args) -> int:
    from gitgrounded.config.loader import load_config
    from gitgrounded.project import find_project
    from gitgrounded.sources.variant import cleanup_worktrees
    from gitgrounded.store.cache import Cache

    project = find_project(config=args.config)
    cfg = load_config(project.config_path)
    project = project.with_state_dir(cfg.project.state_dir)
    n = Cache(project.cache_dir).clear()
    w = cleanup_worktrees(project)
    console.print(f"cleared {n} cache entries and {w} worktrees")
    return 0


def cmd_schema(args) -> int:
    from gitgrounded.config.loader import config_json_schema

    print(json.dumps(config_json_schema(), indent=2))
    return 0


def cmd_init(args) -> int:
    from gitgrounded.cli.init import init_project

    return init_project(Path.cwd(), args.force)


def _add_common(p, outputs: bool = True) -> None:
    p.add_argument("--config", help="path to gitgrounded.yml (default: search upward from cwd)")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--format", choices=["terminal", "json", "markdown"], default="terminal")
    if outputs:
        p.add_argument("--suite")
        p.add_argument("--trials", type=int)
        p.add_argument(
            "--quick", action="store_true", help="run at most 6 cases, prioritizing those related to the change"
        )
        p.add_argument("--max-cases", type=int)
        p.add_argument("--case", help="comma separated case ids to run")
        p.add_argument("--no-generate", action="store_true", help="skip diff targeted case generation")
        p.add_argument("--budget-usd", type=float)
        p.add_argument("--concurrency", type=int)
        p.add_argument("--fail-on", choices=["fail", "warn", "never"], default="fail")
        p.add_argument("--html", help="write the HTML report here")
        p.add_argument("--markdown", help="write the Markdown summary here")
        p.add_argument("--junit", help="write JUnit XML here")
        p.add_argument("--json-out", help="write the full result JSON here")
        p.add_argument("--bundle", nargs="?", const="auto", help="write a signed evidence bundle (.ggb); optional path")
        p.add_argument("--sign", choices=["auto", "sigstore", "local", "none"])
        p.add_argument("--open", action="store_true", help="open the HTML report")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitgrounded",
        description="Auto generated benchmarks, change targeted regression tests and signed evidence for LLM apps",
    )
    parser.add_argument("--version", action="version", version=f"gitgrounded {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create gitgrounded.yml and a starter cases file")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("run", help="compare two git refs of your app")
    p.add_argument("--base", default="HEAD", help="baseline ref (default HEAD)")
    p.add_argument("--head", default="@worktree", help="candidate ref; @worktree tests uncommitted changes (default)")
    p.add_argument("--minimal", action="store_true", help="use the mutation minimized suite")
    p.add_argument("--certify", action="store_true", help="run judge traps and write a signed certificate")
    p.add_argument("--out", help="certificate path (.ggb)")
    _add_common(p)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("compare", help="compare prompts across models on a locked AI generated question set")
    p.add_argument(
        "--prompt", action="append", required=True, help="prompt file or inline text; repeat for each prompt"
    )
    p.add_argument(
        "--model",
        action="append",
        help="provider or provider:model; repeat or comma separate (default GITGROUNDED_TARGET_MODELS)",
    )
    p.add_argument("--context", action="append", help="policy or knowledge file the answers must be grounded in")
    p.add_argument("--baseline", type=int, default=0, help="index of the baseline candidate in the grid")
    p.add_argument("--budget-cases", type=int, default=40)
    p.add_argument("--regenerate", action="store_true", help="regenerate the locked question set")
    p.add_argument("--json-mode", action="store_true")
    p.add_argument("--certify", action="store_true", help="run judge traps and write a signed certificate")
    p.add_argument("--out", help="certificate path (.ggb)")
    _add_common(p)
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser(
        "benchmark",
        help="benchmark any targets (frameworks, agents, APIs, MCP) on one locked AI generated question set",
    )
    p.add_argument("--target", action="append", help="target name from gitgrounded.yml; repeat (default: all targets)")
    p.add_argument("--spec", action="append", help="system prompt or task description file used to generate questions")
    p.add_argument("--context", action="append", help="policy or knowledge file the answers must be grounded in")
    p.add_argument("--baseline", type=int, default=0)
    p.add_argument("--budget-cases", type=int, default=40)
    p.add_argument("--regenerate", action="store_true")
    p.add_argument("--certify", action="store_true")
    p.add_argument("--out")
    _add_common(p)
    p.set_defaults(fn=cmd_benchmark)

    p = sub.add_parser("doctor", help="show configured providers and roles; --ping tests each one")
    p.add_argument("--ping", action="store_true")
    _add_common(p, outputs=False)
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("check", help="check live HTTP endpoints against their stored history")
    p.add_argument("target", nargs="?", help="target name from gitgrounded.yml")
    p.add_argument("--url", help='ad hoc endpoint URL (POST {"message": ...})')
    p.add_argument("--output", help="JSONPath of the answer in the response, for --url")
    p.add_argument("--label", help="history label (default: target name or URL)")
    p.add_argument("--cases", help="cases file (JSONL or JSON)")
    _add_common(p)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("rank", help="rank several candidate refs against one baseline")
    p.add_argument("--base", required=True)
    p.add_argument("candidates", nargs="+")
    _add_common(p)
    p.set_defaults(fn=cmd_rank)

    p = sub.add_parser("history", help="list, inspect or delete endpoint history")
    p.add_argument("label", nargs="?", help="'list', 'delete', 'import', or a label to inspect")
    p.add_argument("target", nargs="?", help="label to delete")
    p.add_argument("--version", type=int)
    p.add_argument("--all", action="store_true")
    p.add_argument("--rank", action="store_true")
    p.add_argument("--config")
    p.set_defaults(fn=cmd_history)

    p = sub.add_parser("discover", help="extract testable behaviors from the system prompt, documents and tools")
    _add_common(p, outputs=False)
    p.add_argument("--suite")
    p.set_defaults(fn=cmd_discover)

    p = sub.add_parser("synth", help="generate or update the benchmark suite automatically")
    _add_common(p, outputs=False)
    p.add_argument("--suite")
    p.add_argument("--full", action="store_true", help="regenerate every behavior instead of only changed ones")
    p.add_argument("--no-logs", action="store_true")
    p.add_argument("--concurrency", type=int)
    p.add_argument("--budget-usd", type=float)
    p.set_defaults(fn=cmd_synth)

    p = sub.add_parser("mutate", help="measure suite strength by injecting faults into the prompt")
    _add_common(p, outputs=False)
    p.add_argument("--suite")
    p.add_argument("--ref", default="@worktree")
    p.add_argument("--no-repair", action="store_true")
    p.add_argument("--max-mutants", type=int)
    p.add_argument("--fail-on", choices=["target", "never"], default="never")
    p.add_argument("--concurrency", type=int)
    p.add_argument("--budget-usd", type=float)
    p.set_defaults(fn=cmd_mutate)

    p = sub.add_parser("suite", help="review, inspect or import suites")
    p.add_argument("action", choices=["review", "coverage", "show", "import"])
    p.add_argument("--suite")
    p.add_argument("--port", type=int, default=8799)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--all", action="store_true", help="review already reviewed cases too")
    p.add_argument("--html")
    p.add_argument("--open", action="store_true")
    p.add_argument("--file")
    p.add_argument("--out")
    _add_common(p, outputs=False)
    p.set_defaults(fn=cmd_suite)

    p = sub.add_parser("report", help="render a stored run")
    p.add_argument("result", nargs="?", default="latest", help="result.json, run directory or 'latest'")
    p.add_argument("--format", choices=["terminal", "html", "markdown", "junit", "json"], default="terminal")
    p.add_argument("--out")
    p.add_argument("--open", action="store_true")
    p.add_argument("--config")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("bundle", help="build a signed evidence bundle for a stored run")
    p.add_argument("result", nargs="?", default="latest")
    p.add_argument("--out")
    p.add_argument("--sign", choices=["auto", "sigstore", "local", "none"])
    p.add_argument("--config")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(fn=cmd_bundle)

    p = sub.add_parser("certifier", help="run or inspect an independent certification service")
    p.add_argument("action", choices=["serve", "pubkey"])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--home", default=".gitgrounded-certifier", help="directory for jobs, certificates and the service key"
    )
    p.add_argument("--key", help="ed25519 private key file (default: <home>/certifier_ed25519.pem)")
    p.add_argument("--name", default="gitgrounded-certifier")
    p.add_argument("--public-url", help="public URL of this service, recorded in certificates")
    p.add_argument("--max-cases", type=int, default=200)
    p.add_argument("--allow-private", action="store_true", help="allow http and private network targets (testing only)")
    p.set_defaults(fn=cmd_certifier)

    p = sub.add_parser("certify-remote", help="have an independent certifier benchmark and sign a remote target")
    p.add_argument("--service", required=True, help="certifier URL")
    p.add_argument("--target", required=True, help="remote target name from gitgrounded.yml (http, a2a, adk, mcp http)")
    p.add_argument("--spec", action="append")
    p.add_argument("--context", action="append")
    p.add_argument("--budget-cases", type=int, default=40)
    p.add_argument("--name")
    p.add_argument("--token", help="API token (default: GITGROUNDED_CERTIFIER_TOKEN)")
    p.add_argument("--expect-key", help="pin the certifier key id or base64 public key")
    p.add_argument("--timeout", type=float, default=3600.0)
    p.add_argument("--out")
    p.add_argument("--config")
    p.set_defaults(fn=cmd_certify_remote)

    p = sub.add_parser("verify", help="verify an evidence bundle")
    p.add_argument("bundle")
    p.add_argument(
        "--identity",
        help="expected signer identity, e.g. https://github.com/OWNER/REPO/.github/workflows/gitgrounded.yml@refs/heads/main",
    )
    p.add_argument("--issuer", default="https://token.actions.githubusercontent.com")
    p.add_argument("--public-key", help="expected ed25519 key id or base64 public key for self signed bundles")
    p.add_argument("--format", choices=["terminal", "json"], default="terminal")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("calibrate", help="measure judge agreement with human labels")
    p.add_argument(
        "--labels", required=True, help="JSONL with input, output, expectations and score (0-10) and/or pass"
    )
    p.add_argument("--rubric", default="grounded_answer")
    p.add_argument("--threshold", type=float, default=6.0)
    _add_common(p, outputs=False)
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("mcp", help="MCP server tools: schema diff and GitGrounded as an MCP server")
    p.add_argument("action", choices=["diff", "serve"])
    p.add_argument("--base", default="HEAD")
    p.add_argument("--head", default="@worktree")
    p.add_argument("--target")
    p.add_argument("--old-file")
    p.add_argument("--new-file")
    p.add_argument("--threshold", type=float, default=0.85)
    p.add_argument("--fail-on", choices=["breaking", "risky", "never"], default="breaking")
    p.add_argument("--project-dir")
    _add_common(p, outputs=False)
    p.set_defaults(fn=cmd_mcp)

    p = sub.add_parser("cache", help="cache maintenance")
    p.add_argument("action", choices=["clear"])
    p.add_argument("--config")
    p.set_defaults(fn=cmd_cache)

    p = sub.add_parser("schema", help="print the JSON schema of gitgrounded.yml")
    p.set_defaults(fn=cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    reject_removed(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code = args.fn(args)
    except GitGroundedError as e:
        err.print(f"[red]error:[/red] {e}")
        code = 2
    except KeyboardInterrupt:
        err.print("interrupted")
        code = 130
    sys.exit(code)
