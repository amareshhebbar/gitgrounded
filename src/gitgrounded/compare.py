import difflib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gitgrounded.canonical import content_hash, sha256_hex
from gitgrounded.config.schema import (
    CoverageCfg,
    CoverageSources,
    GenerateCfg,
    JudgeCfg,
    OpenAIChatTarget,
    ProviderCfg,
    SuiteCfg,
)
from gitgrounded.coverage.pipeline import CoveragePipeline
from gitgrounded.coverage.suite_store import SuiteStore, suite_integrity
from gitgrounded.engine import Engine, RunOptions
from gitgrounded.errors import ConfigError
from gitgrounded.providers import env
from gitgrounded.report.model import RunResult
from gitgrounded.sources.variant import Variant

TARGET = "__compare__"


@dataclass
class PromptSpec:
    name: str
    text: str
    path: str


@dataclass
class Candidate:
    name: str
    prompt: PromptSpec
    model: dict[str, Any]

    def variant(self, root: Path) -> Variant:
        return Variant(
            name=self.name,
            root=root,
            files={},
            content_hash=content_hash({"prompt": self.prompt.text, "model": self.model}),
            kind="candidate",
            overlay={"system_prompt": self.prompt.text, "model": self.model},
        )


@dataclass
class CompareResult:
    suite: str
    suite_version: str | None
    cases: list
    candidates: list[Candidate]
    baseline: str
    leaderboard: list[dict[str, Any]]
    results: list[tuple[str, RunResult]] = field(default_factory=list)


def load_prompts(engine: Engine, specs: list[str]) -> list[PromptSpec]:
    out = []
    store = engine.project.state_dir / "compare" / "prompts"
    for i, spec in enumerate(specs):
        p = engine.project.resolve(spec)
        if len(spec) < 400 and p.is_file():
            out.append(PromptSpec(p.stem, p.read_text(encoding="utf-8"), str(p)))
            continue
        store.mkdir(parents=True, exist_ok=True)
        f = store / f"{sha256_hex(spec)[:12]}.txt"
        f.write_text(spec, encoding="utf-8")
        out.append(PromptSpec(f"prompt{i + 1}", spec, str(f)))
    names = [p.name for p in out]
    for i, p in enumerate(out):
        if names.count(p.name) > 1:
            p.name = f"{p.name}{i + 1}"
    return out


def parse_models(specs: list[str]) -> list[dict[str, Any]]:
    models = []
    for s in specs:
        for part in env.split_specs(s):
            models.append(env.parse_spec(part))
    if not models:
        models = env.target_models()
    if not models:
        raise ConfigError(
            "no models given; pass --model claude --model openai or set GITGROUNDED_TARGET_MODELS in .env"
        )
    return models


def model_label(m: dict[str, Any]) -> str:
    return f"{m['provider']}:{m['model']}"


def build_grid(prompts: list[PromptSpec], models: list[dict[str, Any]]) -> list[Candidate]:
    grid = []
    for p in prompts:
        for m in models:
            name = (
                p.name if len(models) == 1 else (model_label(m) if len(prompts) == 1 else f"{p.name}@{model_label(m)}")
            )
            grid.append(Candidate(name, p, m))
    return grid


def _diff(a: Candidate, b: Candidate) -> str:
    lines = list(
        difflib.unified_diff(
            a.prompt.text.splitlines(keepends=True),
            b.prompt.text.splitlines(keepends=True),
            fromfile=f"a/{a.prompt.name}",
            tofile=f"b/{b.prompt.name}",
        )
    )
    if a.model != b.model:
        lines.append(f"--- a/model\n+++ b/model\n-{model_label(a.model)}\n+{model_label(b.model)}\n")
    return "".join(lines)


def configure(
    engine: Engine,
    prompts: list[PromptSpec],
    models: list[dict[str, Any]],
    context: list[str],
    budget: int,
    min_per: int,
    template: str | None,
    trials: int,
    json_mode: bool,
) -> str:
    cfg = engine.cfg
    cfg.targets[TARGET] = OpenAIChatTarget(
        type="openai_chat", system_prompt="", model=ProviderCfg(**models[0]), json_mode=json_mode
    )
    docs = [engine.project.rel(engine.project.resolve(c)) for c in context]
    for d in docs:
        if not engine.project.resolve(d).exists():
            raise ConfigError(f"context file not found: {d}")
    key = content_hash(
        {
            "prompts": sorted(p.text for p in prompts),
            "docs": [engine.project.resolve(d).read_text(encoding="utf-8", errors="replace") for d in docs],
            "generator": cfg.providers.generator.model_dump(mode="json"),
            "budget": budget,
            "min": min_per,
        }
    )
    name = f"compare-{key[:12]}"
    judges = [
        JudgeCfg(type="rubric", rubric="grounded_answer" if docs else "instruction_following"),
        JudgeCfg(type="pairwise"),
    ]
    assertions: list = []
    ctx = {f"doc{i + 1}": d for i, d in enumerate(docs)}
    if template:
        _, t = cfg.suite(template)
        judges, assertions, ctx = list(t.judges), list(t.assertions), {**t.context, **ctx}
    cfg.suites[name] = SuiteCfg(
        target=TARGET,
        assertions=assertions,
        judges=judges,
        trials=trials,
        context=ctx,
        generate=GenerateCfg(enabled=False),
        coverage=CoverageCfg(
            sources=CoverageSources(prompts=[p.path for p in prompts], documents=docs),
            budget_cases=budget,
            min_cases_per_behavior=min_per,
        ),
    )
    return name


def _row(
    name: str, cand: Candidate, metrics: dict, side: str, cost: dict, latency: dict, result: RunResult | None
) -> dict[str, Any]:
    score = (metrics.get("score") or {}).get(side) or {}
    apr = (metrics.get("assertion_pass_rate") or {}).get(side) or {}
    row = {
        "candidate": name,
        "prompt": cand.prompt.name,
        "model": model_label(cand.model),
        "score_mean": score.get("mean"),
        "ci_lower": score.get("ci_lower"),
        "ci_upper": score.get("ci_upper"),
        "assertion_pass_rate": apr.get("rate"),
        "cost_usd": (cost.get(side) or {}).get("usd"),
        "p50_ms": (latency.get(side) or {}).get("p50_ms"),
        "verdict_vs_baseline": None,
        "delta": None,
        "p_adjusted": None,
        "win_rate": None,
        "loss_rate": None,
    }
    if result is not None and side == "head" and result.base is not None:
        d = (metrics.get("score") or {}).get("delta") or {}
        row.update(
            verdict_vs_baseline=result.verdict,
            delta=d.get("mean"),
            p_adjusted=d.get("p_adjusted"),
            win_rate=result.pairwise.get("head_win_rate"),
            loss_rate=result.pairwise.get("base_win_rate"),
        )
    return row


def leaderboard(
    candidates: list[Candidate], baseline: Candidate, results: list[tuple[str, RunResult]]
) -> list[dict[str, Any]]:
    rows = []
    by_name = {c.name: c for c in candidates}
    if results:
        first = results[0][1]
        if first.base is not None:
            base_row = _row(baseline.name, baseline, first.metrics, "base", first.cost, first.latency, None)
            base_row["verdict_vs_baseline"] = "BASELINE"
            rows.append(base_row)
        for name, r in results:
            rows.append(_row(name, by_name[name], r.metrics, "head", r.cost, r.latency, r))
    rows.sort(key=lambda r: (-(r["assertion_pass_rate"] or 0.0), -(r["score_mean"] or 0.0)))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def run_compare(
    engine: Engine,
    prompt_specs: list[str],
    model_specs: list[str],
    context: list[str] | None = None,
    baseline: int = 0,
    budget: int = 40,
    min_per: int = 2,
    regenerate: bool = False,
    quick: bool = False,
    trials: int = 1,
    json_mode: bool = False,
    template: str | None = None,
    log: Callable[[str], None] | None = None,
) -> CompareResult:
    log = log or (lambda m: None)
    prompts = load_prompts(engine, prompt_specs)
    models = parse_models(model_specs)
    candidates = build_grid(prompts, models)
    if not 0 <= baseline < len(candidates):
        raise ConfigError(f"--baseline must be between 0 and {len(candidates) - 1}")
    name = configure(engine, prompts, models, context or [], budget, min_per, template, trials, json_mode)
    store = SuiteStore(engine.project, name)
    sealed, why = suite_integrity(store)
    if regenerate or not store.exists():
        log(f"generating locked question set {name} from {len(prompts)} prompt(s)")
        CoveragePipeline(engine, name, log=log).synth(incremental=False)
    elif not sealed:
        raise ConfigError(f"locked suite {name} was modified ({why}); rerun with --regenerate")
    else:
        log(f"reusing locked question set {name}")
    cases = store.cases()
    if quick:
        cases = engine.select_cases(cases, RunOptions(quick=True))
    opts = RunOptions(write=False, generate=False, trials=trials)
    root = engine.project.root
    base = candidates[baseline]
    results: list[tuple[str, RunResult]] = []
    if len(candidates) == 1:
        r = engine.run_variants(name, None, base.variant(root), "", opts, mode="compare", cases=cases)
        engine.write_result(r)
        results.append((base.name, r))
        rows = [_row(base.name, base, r.metrics, "head", r.cost, r.latency, None)]
        rows[0]["rank"] = 1
        rows[0]["verdict_vs_baseline"] = r.verdict
    else:
        for cand in candidates:
            if cand is base:
                continue
            log(f"comparing {base.name} -> {cand.name}")
            r = engine.run_variants(
                name, base.variant(root), cand.variant(root), _diff(base, cand), opts, mode="compare", cases=cases
            )
            engine.write_result(r)
            results.append((cand.name, r))
        rows = leaderboard(candidates, base, results)
    return CompareResult(name, store.meta().get("version"), cases, candidates, base.name, rows, results)


def run_benchmark(
    engine: Engine,
    target_names: list[str],
    spec_files: list[str],
    context: list[str] | None = None,
    baseline: int = 0,
    budget: int = 40,
    min_per: int = 2,
    regenerate: bool = False,
    quick: bool = False,
    trials: int = 1,
    template: str | None = None,
    log: Callable[[str], None] | None = None,
) -> CompareResult:
    import time as _time

    from gitgrounded.exec.executor import Executor

    log = log or (lambda m: None)
    names = target_names or [t for t in engine.cfg.targets if t != TARGET]
    if not names:
        raise ConfigError("no targets; add targets to gitgrounded.yml or pass --target")
    for n in names:
        engine.cfg.target(n)
    if not 0 <= baseline < len(names):
        raise ConfigError(f"--baseline must be between 0 and {len(names) - 1}")
    prompts = load_prompts(engine, spec_files) if spec_files else []
    if not prompts and not context:
        raise ConfigError(
            "pass --spec (system prompt or task description files) and/or --context so questions can be generated"
        )
    name = configure(
        engine,
        prompts,
        [{"provider": "mock", "model": "mock"}],
        context or [],
        budget,
        min_per,
        template,
        trials,
        False,
    )
    engine.cfg.suites[name] = engine.cfg.suites[name].model_copy(update={"target": names[0]})
    _, suite = engine.cfg.suite(name)
    store = SuiteStore(engine.project, name)
    sealed, why = suite_integrity(store)
    if regenerate or not store.exists():
        log(f"generating locked question set {name}")
        CoveragePipeline(engine, name, log=log).synth(incremental=False)
    elif not sealed:
        raise ConfigError(f"locked suite {name} was modified ({why}); rerun with --regenerate")
    cases = store.cases()
    if quick:
        cases = engine.select_cases(cases, RunOptions(quick=True))
    trs = {}
    for n in names:
        target = engine.target(n)
        log(f"running {len(cases)} cases on {n} ({target.describe().get('kind')})")
        v = Variant(
            name=n,
            root=engine.project.root,
            files={},
            content_hash=content_hash({"t": n, "at": _time.time()}),
            kind="live",
        )
        trs[n] = Executor.from_config(target, engine.cache, engine.cfg.execution, use_cache=False).run(v, cases, trials)
    ctx = engine.context_text(suite, None)
    cands = [
        Candidate(
            n,
            PromptSpec(str(engine.target(n).describe().get("framework") or engine.cfg.target(n).type), "", ""),
            {"provider": engine.cfg.target(n).type, "model": n},
        )
        for n in names
    ]
    base = cands[baseline]
    results: list[tuple[str, RunResult]] = []

    def desc(n: str) -> dict[str, Any]:
        return {"name": n, **engine.target(n).describe()}

    if len(names) == 1:
        r = engine.evaluate(
            name,
            suite,
            cases,
            None,
            trs[base.name],
            trials,
            ctx,
            ctx,
            mode="benchmark",
            base_desc=None,
            head_desc=desc(base.name),
            target=engine.target(base.name),
        )
        engine.write_result(r)
        results.append((base.name, r))
        rows = [_row(base.name, base, r.metrics, "head", r.cost, r.latency, None)]
        rows[0].update(rank=1, verdict_vs_baseline=r.verdict)
    else:
        for c in cands:
            if c is base:
                continue
            log(f"evaluating {base.name} -> {c.name}")
            r = engine.evaluate(
                name,
                suite,
                cases,
                trs[base.name],
                trs[c.name],
                trials,
                ctx,
                ctx,
                mode="benchmark",
                base_desc=desc(base.name),
                head_desc=desc(c.name),
                target=engine.target(c.name),
            )
            engine.write_result(r)
            results.append((c.name, r))
        rows = leaderboard(cands, base, results)
    return CompareResult(name, store.meta().get("version"), cases, cands, base.name, rows, results)
