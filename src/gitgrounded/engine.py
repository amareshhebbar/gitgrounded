import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from gitgrounded import __version__
from gitgrounded.assertions.builtin import oracle_assertions, run_assertions, set_base_dir
from gitgrounded.canonical import content_hash
from gitgrounded.cases.generate import generate_diff_cases
from gitgrounded.cases.loader import load_cases
from gitgrounded.cases.model import Case, dataset_hash
from gitgrounded.config.schema import Config, SuiteCfg
from gitgrounded.errors import ConfigError
from gitgrounded.exec.executor import Executor
from gitgrounded.gates import decide
from gitgrounded.judges.pairwise import PairwiseJudge
from gitgrounded.judges.rubric import RubricJudge, load_rubric
from gitgrounded.project import Project
from gitgrounded.providers.usage import USAGE
from gitgrounded.report.model import RunResult
from gitgrounded.sources.variant import Variant, diff_text, materialize
from gitgrounded.stats.cost import transcript_cost
from gitgrounded.stats.intervals import bootstrap_mean_ci, wilson
from gitgrounded.stats.reliability import krippendorff_alpha_interval, position_consistency
from gitgrounded.stats.significance import holm, paired_bootstrap_delta, sign_flip_p_value
from gitgrounded.store.cache import Cache
from gitgrounded.store.history import History
from gitgrounded.targets.base import Target, Transcript, build_target

FAIL_DROP = 3.0
FAIL_DROP_WITH_PAIRWISE = 1.5
WARN_DROP = 1.0
IMPROVE_GAIN = 1.0
ABSOLUTE_WARN = 5.0
ABSOLUTE_FAIL = 3.0


@dataclass
class RunOptions:
    trials: int | None = None
    quick: bool = False
    max_cases: int | None = None
    generate: bool | None = None
    write: bool = True
    use_transcript_cache: bool = True
    case_ids: list[str] | None = None
    progress: Callable[[str], None] | None = None
    extra_cases: list[Case] = field(default_factory=list)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _percentile(values: list[float], q: float) -> float | None:
    vals = [v for v in values if v is not None]
    return float(np.percentile(vals, q)) if vals else None


def _majority(items: list[str]) -> str:
    if not items:
        return "tie"
    counts = {k: items.count(k) for k in set(items)}
    best = max(counts.values())
    winners = [k for k, v in counts.items() if v == best]
    return winners[0] if len(winners) == 1 else "tie"


class Engine:
    def __init__(self, project: Project, cfg: Config, log: Callable[[str], None] | None = None):
        self.project = project.with_state_dir(cfg.project.state_dir)
        self.cfg = cfg
        self.cache = Cache(self.project.cache_dir)
        self.history = History(self.project.history_dir)
        self.log = log or (lambda msg: None)
        self._targets: dict[str, Target] = {}
        USAGE.configure(cfg.prices, cfg.execution.budget_usd)
        set_base_dir(self.project.root)

    def target(self, name: str) -> Target:
        if name not in self._targets:
            self._targets[name] = build_target(name, self.cfg.target(name), self.project)
        return self._targets[name]

    def close(self) -> None:
        for t in self._targets.values():
            t.close()
        self._targets.clear()

    def suite_cases_path(self, suite_name: str, suite: SuiteCfg) -> Path:
        if suite.cases:
            return self.project.resolve(suite.cases)
        return self.project.suites_dir / suite_name / "current.jsonl"

    def load_suite_cases(self, suite_name: str, suite: SuiteCfg) -> tuple[list[Case], str | None]:
        path = self.suite_cases_path(suite_name, suite)
        if not path.exists():
            raise ConfigError(
                f"suite '{suite_name}' has no cases at {self.project.rel(path)}; run `gitgrounded synth --suite {suite_name}` or point suites.{suite_name}.cases at a JSONL file"
            )
        cases = load_cases(path)
        version = None
        meta = path.parent / "suite.json"
        if meta.exists():
            try:
                version = json.loads(meta.read_text(encoding="utf-8")).get("version")
            except (OSError, ValueError):
                version = None
        return cases, version

    def watch_paths(self, suite: SuiteCfg) -> list[str]:
        tcfg = self.cfg.target(suite.target)
        paths = list(getattr(tcfg, "watch", []) or [])
        for attr in ("system_prompt_file", "model_file", "tools_file"):
            v = getattr(tcfg, attr, None)
            if v and v not in paths:
                paths.append(v)
        for v in getattr(tcfg, "template_vars", {}).values() if hasattr(tcfg, "template_vars") else []:
            if v not in paths:
                paths.append(v)
        return paths

    def context_text(self, suite: SuiteCfg, variant: Variant | None) -> str:
        parts = []
        for name, path in suite.context.items():
            text = None
            if variant is not None:
                text = variant.files.get(path)
                if text is None and (variant.root / path).exists():
                    text = (variant.root / path).read_text(encoding="utf-8", errors="replace")
            if text is None:
                p = self.project.resolve(path)
                text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
            parts.append(f"## {name}\n{text}")
        return "\n\n".join(parts)

    def build_judges(self, suite: SuiteCfg) -> tuple[list[RubricJudge], PairwiseJudge | None]:
        rubric_judges: list[RubricJudge] = []
        pairwise = None
        for j in suite.judges:
            pcfg = j.provider or self.cfg.providers.judge
            if j.type == "rubric":
                rubric = load_rubric(j.rubric, self.project.root)
                rubric_judges.append(RubricJudge(rubric, pcfg, self.cache))
                for extra in self.cfg.providers.panel:
                    rubric_judges.append(RubricJudge(rubric, extra, self.cache))
            elif j.type == "pairwise":
                pairwise = PairwiseJudge(pcfg, self.cache, swap=j.swap)
        return rubric_judges, pairwise

    def select_cases(self, cases: list[Case], opts: RunOptions, diff: str = "") -> list[Case]:
        if opts.case_ids:
            wanted = set(opts.case_ids)
            cases = [c for c in cases if c.id in wanted]
        limit = opts.max_cases or (6 if opts.quick else None)
        if limit and len(cases) > limit:
            changed = _changed_lines(diff)
            if changed:
                scored = sorted(cases, key=lambda c: -_relevance(c, changed))
            else:
                scored = cases
            seen_behaviors: set[str] = set()
            picked: list[Case] = []
            for c in scored:
                key = c.behaviors[0] if c.behaviors else c.id
                if key not in seen_behaviors:
                    picked.append(c)
                    seen_behaviors.add(key)
                if len(picked) >= limit:
                    break
            for c in scored:
                if len(picked) >= limit:
                    break
                if c not in picked:
                    picked.append(c)
            cases = picked
        return cases

    def run_git(
        self, suite_name: str | None, base_ref: str, head_ref: str, opts: RunOptions | None = None
    ) -> RunResult:
        opts = opts or RunOptions()
        suite_name, suite = self.cfg.suite(suite_name)
        watch = self.watch_paths(suite)
        self.log(f"materializing {base_ref} and {head_ref}")
        base = materialize(self.project, base_ref, watch)
        head = materialize(self.project, head_ref, watch)
        diff = diff_text(self.project, base, head, watch)
        return self.run_variants(suite_name, base, head, diff, opts, mode="git")

    def run_variants(
        self,
        suite_name: str,
        base: Variant | None,
        head: Variant,
        diff: str,
        opts: RunOptions,
        mode: str = "git",
        cases: list[Case] | None = None,
        base_transcripts: dict | None = None,
    ) -> RunResult:
        _, suite = self.cfg.suite(suite_name)
        suite_version = None
        if cases is None:
            cases, suite_version = self.load_suite_cases(suite_name, suite)
        cases = self.select_cases(cases, opts, diff) + list(opts.extra_cases)
        generated: list[Case] = []
        gen_enabled = suite.generate.enabled if opts.generate is None else opts.generate
        if gen_enabled and diff.strip() and base is not None:
            count = 2 if opts.quick else suite.generate.count
            self.log(f"generating up to {count} diff targeted cases")
            generated = generate_diff_cases(
                self.cfg.providers.generator, self.cache, diff, suite.generate.domain, cases, count
            )
            cases = cases + generated
        if not cases:
            raise ConfigError("no cases to run")
        trials = opts.trials or suite.trials
        target = self.target(suite.target)
        use_cache = opts.use_transcript_cache and target.kind != "http"
        executor = Executor.from_config(target, self.cache, self.cfg.execution, use_cache=use_cache)
        head_trs = None
        if base is not None and base_transcripts is None:
            self.log(f"running {len(cases)} cases x {trials} trials on base {base.name}")
            base_transcripts = executor.run(base, cases, trials)
        self.log(f"running {len(cases)} cases x {trials} trials on head {head.name}")
        head_trs = executor.run(head, cases, trials)
        context_base = self.context_text(suite, base) if base is not None else ""
        context_head = self.context_text(suite, head)
        result = self.evaluate(
            suite_name,
            suite,
            cases,
            base_transcripts,
            head_trs,
            trials,
            context_base,
            context_head,
            mode=mode,
            base_desc=base.describe() if base is not None else None,
            head_desc=head.describe(),
            diff=diff,
            generated=generated,
            suite_version=suite_version,
            target=target,
        )
        if opts.write:
            self.write_result(result)
        return result

    def evaluate(
        self,
        suite_name: str,
        suite: SuiteCfg,
        cases: list[Case],
        base_trs: dict[tuple[str, int], Transcript] | None,
        head_trs: dict[tuple[str, int], Transcript],
        trials: int,
        context_base: str,
        context_head: str,
        mode: str,
        base_desc: dict | None,
        head_desc: dict,
        diff: str = "",
        generated: list[Case] | None = None,
        suite_version: str | None = None,
        target: Target | None = None,
    ) -> RunResult:
        rubric_judges, pairwise = self.build_judges(suite)
        specs = [a.model_dump() for a in suite.assertions]
        self.log(f"evaluating {len(cases)} cases")

        def variant_eval(case: Case, trs: dict, ctx: str) -> dict[str, Any]:
            per_trial = []
            for t in range(trials):
                tr = trs.get((case.id, t))
                if tr is None:
                    continue
                checks = run_assertions(specs + case.assertions + oracle_assertions(case), tr, case)
                judged = [j.evaluate(case, tr, ctx) for j in rubric_judges]
                per_trial.append({"transcript": tr, "assertions": checks, "judges": judged})
            fail_trials = sum(1 for p in per_trial if any(not a.passed for a in p["assertions"]))
            dims: dict[str, list[float]] = {}
            judge_scores: dict[str, list[float]] = {}
            for p in per_trial:
                for jr in p["judges"]:
                    for k, v in jr.scores.items():
                        dims.setdefault(k, []).append(v)
                    judge_scores.setdefault(jr.judge + "|" + (jr.model or ""), []).append(jr.score)
                    dims.setdefault("score", []).append(jr.score)
            scores = {k: float(np.mean(v)) for k, v in dims.items()}
            return {
                "trials": per_trial,
                "fail_trials": fail_trials,
                "failed": fail_trials * 2 > len(per_trial) if per_trial else True,
                "flaky": 0 < fail_trials < len(per_trial),
                "scores": scores,
                "judge_scores": {k: float(np.mean(v)) for k, v in judge_scores.items()},
            }

        def one(case: Case) -> dict[str, Any]:
            head = variant_eval(case, head_trs, context_head)
            base = variant_eval(case, base_trs, context_base) if base_trs is not None else None
            pw_results = []
            if base is not None and pairwise is not None:
                for t in range(trials):
                    b, h = base_trs.get((case.id, t)), head_trs.get((case.id, t))
                    if b is not None and h is not None:
                        pw_results.append(pairwise.compare(case, b, h, context_head))
            return _case_result(case, base, head, pw_results)

        with ThreadPoolExecutor(max_workers=max(1, self.cfg.execution.max_concurrency)) as pool:
            case_results = list(pool.map(one, cases))

        counts = _counts(case_results, base_trs is not None)
        metrics = _metrics(
            case_results, self.cfg.execution.bootstrap_iterations, self.cfg.execution.seed, base_trs is not None
        )
        pw_summary = _pairwise_summary(case_results)
        reliability = _reliability(case_results, pw_summary)
        cost = _cost(case_results, self.cfg.prices)
        latency = _latency(case_results)
        behaviors = _behavior_summary(case_results)
        ns = {
            **counts,
            "delta": {k: v.get("delta", {}) for k, v in metrics.items()},
            "head": {k: v.get("head", {}) for k, v in metrics.items()},
            "base": {k: v.get("base", {}) for k, v in metrics.items()},
            "pairwise": pw_summary,
            "cost": cost,
            "latency": latency,
        }
        if base_trs is None:
            verdict, trace = _absolute_verdict(counts)
        else:
            verdict, trace = decide(self.cfg.gates.fail_if, self.cfg.gates.warn_if, ns)
        run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
        all_cases = list(cases)
        return RunResult(
            run_id=run_id,
            created_at=_now(),
            tool_version=__version__,
            project=self.cfg.project.name,
            suite=suite_name,
            mode=mode,
            target=(target.describe() if target else {"name": suite.target}),
            base=base_desc,
            head=head_desc,
            diff=diff,
            config_hash=content_hash(self.cfg.model_dump(mode="json")),
            dataset_hash=dataset_hash(all_cases),
            suite_version=suite_version,
            providers={
                "judge": self.cfg.providers.judge.model_dump(mode="json"),
                "generator": self.cfg.providers.generator.model_dump(mode="json"),
                "panel": [p.model_dump(mode="json") for p in self.cfg.providers.panel],
                "offline": _offline(),
            },
            trials=trials,
            verdict=verdict,
            gate_trace=trace,
            counts=counts,
            metrics=metrics,
            pairwise=pw_summary,
            reliability=reliability,
            cost=cost,
            latency=latency,
            behaviors=behaviors,
            cases=case_results,
            generated_cases=[c.model_dump(mode="json") for c in (generated or [])],
            usage=USAGE.snapshot(),
            seeds={
                "bootstrap": self.cfg.execution.seed,
                "bootstrap_iterations": self.cfg.execution.bootstrap_iterations,
            },
        )

    def write_result(self, result: RunResult) -> Path:
        d = self.project.runs_dir / result.run_id
        d.mkdir(parents=True, exist_ok=True)
        path = d / "result.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        (self.project.runs_dir / "latest.txt").write_text(result.run_id, encoding="utf-8")
        result.evidence = (result.evidence or {}) | {"result_path": str(path)}
        return path

    def latest_result_path(self) -> Path | None:
        marker = self.project.runs_dir / "latest.txt"
        if not marker.exists():
            return None
        p = self.project.runs_dir / marker.read_text(encoding="utf-8").strip() / "result.json"
        return p if p.exists() else None

    def run_check(
        self,
        suite_name: str | None,
        label: str | None,
        opts: RunOptions | None = None,
        target_name: str | None = None,
        cases: list[Case] | None = None,
    ) -> RunResult:
        opts = opts or RunOptions()
        if target_name and not suite_name:
            suite = SuiteCfg(target=target_name, generate={"enabled": False})
            suite_name = f"check:{target_name}"
            self.cfg.suites.setdefault(suite_name, suite)
        suite_name, suite = self.cfg.suite(suite_name)
        if cases is None:
            cases, _ = self.load_suite_cases(suite_name, suite)
        cases = self.select_cases(cases, opts)
        label = label or suite.target
        target = self.target(suite.target)
        executor = Executor.from_config(target, self.cache, self.cfg.execution, use_cache=False)
        trials = opts.trials or suite.trials
        head_variant = Variant(
            name="live", root=self.project.root, files={}, content_hash=content_hash({"live": _now()}), kind="live"
        )
        self.log(f"calling {target.describe().get('url', suite.target)} with {len(cases)} cases")
        head_trs = executor.run(head_variant, cases, trials)
        latest = self.history.latest(label)
        base_trs = None
        base_desc = None
        if latest is not None:
            snap = self.history.load(label, latest)
            base_trs = {}
            for d in snap.get("transcripts", []):
                tr = Transcript.from_dict(d)
                base_trs[(tr.case_id, tr.trial)] = tr
            known = {cid for cid, _ in base_trs}
            for c in cases:
                if c.id not in known:
                    for t in range(trials):
                        base_trs[(c.id, t)] = head_trs[(c.id, t)]
            base_desc = {
                "name": f"{label}@v{latest}",
                "kind": "history",
                "version": latest,
                "saved_at": snap.get("saved_at"),
            }
        context = self.context_text(suite, None)
        result = self.evaluate(
            suite_name,
            suite,
            cases,
            base_trs,
            head_trs,
            trials,
            context,
            context,
            mode="check",
            base_desc=base_desc,
            head_desc={"name": "live", "kind": "live", "label": label},
            target=target,
        )
        new_version = self.history.save(
            label,
            {
                "target": suite.target,
                "run_id": result.run_id,
                "verdict": result.verdict,
                "cases": [c.model_dump(mode="json") for c in cases],
                "transcripts": [tr.to_dict() for tr in head_trs.values()],
            },
        )
        result.head["version"] = new_version
        if opts.write:
            self.write_result(result)
        return result


def _offline() -> bool:
    from gitgrounded.providers.base import is_offline

    return is_offline()


def _changed_lines(diff: str) -> list[str]:
    out = []
    for line in (diff or "").splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")) and len(line.strip()) > 3:
            out.append(line[1:].strip().lower())
    return out


def _relevance(case: Case, changed: list[str]) -> float:
    from gitgrounded.providers.heuristics import keywords

    text = " ".join([case.input_text()] + [e.text for e in case.expectations]).lower()
    kws = set(keywords(text))
    score = 0.0
    for line in changed:
        lk = set(keywords(line))
        if lk:
            score = max(score, len(lk & kws) / len(lk))
    src = case.meta.get("source_text", "")
    if src and any(src.lower()[:60] in line or line[:60] in src.lower() for line in changed):
        score += 1.0
    return score


def _serialize_trial(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "transcript": p["transcript"].to_dict(),
        "assertions": [a.to_dict() for a in p["assertions"]],
        "judges": [j.to_dict() for j in p["judges"]],
    }


def _case_result(case: Case, base: dict | None, head: dict, pw: list) -> dict[str, Any]:
    reasons: list[str] = []
    delta: dict[str, float] = {}
    pw_winners = [p.winner for p in pw]
    pw_winner = _majority(pw_winners) if pw else None
    unstable = False
    if base is None:
        score = head["scores"].get("score")
        if head["failed"]:
            status = "FAIL"
            reasons.append("assertion failed")
        elif score is not None and score < ABSOLUTE_FAIL:
            status = "FAIL"
            reasons.append(f"judge score {score:.1f} < {ABSOLUTE_FAIL}")
        elif score is not None and score < ABSOLUTE_WARN:
            status = "WARN"
            reasons.append(f"judge score {score:.1f} < {ABSOLUTE_WARN}")
        else:
            status = "PASS"
        if head["flaky"]:
            unstable = True
    else:
        for k in set(base["scores"]) | set(head["scores"]):
            if k in base["scores"] and k in head["scores"]:
                delta[k] = head["scores"][k] - base["scores"][k]
        d = delta.get("score", 0.0)
        new_fail = head["failed"] and not base["failed"]
        fixed = base["failed"] and not head["failed"]
        if head["flaky"] or base["flaky"] or ("head" in pw_winners and "base" in pw_winners):
            unstable = True
        if new_fail:
            status = "FAIL"
            reasons.append("new assertion failure")
        elif head["failed"] and base["failed"]:
            status = "BROKEN"
            reasons.append("assertion fails in both versions")
        elif d <= -FAIL_DROP:
            status = "FAIL"
            reasons.append(f"score dropped {d:.1f}")
        elif pw_winner == "base" and d <= -FAIL_DROP_WITH_PAIRWISE:
            status = "FAIL"
            reasons.append(f"pairwise prefers base and score dropped {d:.1f}")
        elif pw_winner == "base" or d <= -WARN_DROP:
            status = "WARN"
            reasons.append("pairwise prefers base" if pw_winner == "base" else f"score dropped {d:.1f}")
        elif fixed or pw_winner == "head" or d >= IMPROVE_GAIN:
            status = "IMPROVED"
            reasons.append(
                "assertion fixed"
                if fixed
                else ("pairwise prefers head" if pw_winner == "head" else f"score gained {d:.1f}")
            )
        else:
            status = "PASS"
    if unstable and status in ("WARN", "PASS", "IMPROVED"):
        reasons.append("verdict varies across trials")
        status = "UNSTABLE"

    def pack(v: dict | None) -> dict | None:
        if v is None:
            return None
        return {
            "failed": v["failed"],
            "fail_trials": v["fail_trials"],
            "flaky": v["flaky"],
            "scores": v["scores"],
            "judge_scores": v["judge_scores"],
            "trials": [_serialize_trial(p) for p in v["trials"]],
        }

    return {
        "case": case.model_dump(mode="json"),
        "status": status,
        "reasons": reasons,
        "delta": delta,
        "pairwise_winner": pw_winner,
        "pairwise": [p.to_dict() for p in pw],
        "base": pack(base),
        "head": pack(head),
    }


def _counts(results: list[dict], has_base: bool) -> dict[str, int]:
    statuses = [r["status"] for r in results]
    head_fail = sum(1 for r in results if r["head"]["failed"])
    base_fail = sum(1 for r in results if r["base"] and r["base"]["failed"])
    new_fail = (
        sum(1 for r in results if r["head"]["failed"] and (not r["base"] or not r["base"]["failed"]))
        if has_base
        else head_fail
    )
    fixed = sum(1 for r in results if r["base"] and r["base"]["failed"] and not r["head"]["failed"])
    return {
        "total_cases": len(results),
        "pass_cases": statuses.count("PASS"),
        "warn_cases": statuses.count("WARN"),
        "fail_cases": statuses.count("FAIL"),
        "improved_cases": statuses.count("IMPROVED"),
        "broken_cases": statuses.count("BROKEN"),
        "unstable_cases": statuses.count("UNSTABLE"),
        "head_assertion_failures": head_fail,
        "base_assertion_failures": base_fail,
        "new_assertion_failures": new_fail,
        "fixed_assertion_failures": fixed,
        "assertion_failures": head_fail,
        "regressions": statuses.count("FAIL"),
        "improvements": statuses.count("IMPROVED"),
        "errors": sum(1 for r in results for t in r["head"]["trials"] if t["transcript"].get("error")),
    }


def _metrics(results: list[dict], iterations: int, seed: int, has_base: bool) -> dict[str, Any]:
    names: set[str] = set()
    for r in results:
        names |= set(r["head"]["scores"])
    out: dict[str, Any] = {}
    pvals: dict[str, float | None] = {}
    for name in sorted(names):
        head_vals = [r["head"]["scores"].get(name) for r in results]
        entry: dict[str, Any] = {"head": bootstrap_mean_ci([v for v in head_vals if v is not None], iterations, seed)}
        if has_base:
            base_vals = [r["base"]["scores"].get(name) if r["base"] else None for r in results]
            entry["base"] = bootstrap_mean_ci([v for v in base_vals if v is not None], iterations, seed)
            pairs = [(b, h) for b, h in zip(base_vals, head_vals) if b is not None and h is not None]
            delta = paired_bootstrap_delta([p[0] for p in pairs], [p[1] for p in pairs], iterations, seed)
            p = sign_flip_p_value([h - b for b, h in pairs], iterations=max(2000, iterations), seed=seed)
            delta["p_value"] = p
            pvals[name] = p
            entry["delta"] = delta
        out[name] = entry
    if has_base:
        adj = holm(pvals)
        for name, v in adj.items():
            out[name]["delta"]["p_adjusted"] = v
    pass_k = sum(1 for r in results if not r["head"]["failed"])
    out["assertion_pass_rate"] = {"head": wilson(pass_k, len(results))}
    if has_base:
        base_k = sum(1 for r in results if r["base"] and not r["base"]["failed"])
        out["assertion_pass_rate"]["base"] = wilson(base_k, len(results))
    return out


def _pairwise_summary(results: list[dict]) -> dict[str, Any]:
    winners = [r["pairwise_winner"] for r in results if r["pairwise_winner"] is not None]
    n = len(winners)
    if n == 0:
        return {"n": 0}
    head_k, base_k, tie_k = winners.count("head"), winners.count("base"), winners.count("tie")
    flags = [p["consistent"] for r in results for p in r["pairwise"]]
    return {
        "n": n,
        "head_wins": head_k,
        "base_wins": base_k,
        "ties": tie_k,
        "head_win_rate": head_k / n,
        "base_win_rate": base_k / n,
        "tie_rate": tie_k / n,
        "head_win_ci": wilson(head_k, n),
        "base_win_ci": wilson(base_k, n),
        "position_consistency": position_consistency(flags),
    }


def _reliability(results: list[dict], pw: dict) -> dict[str, Any]:
    judge_names: list[str] = []
    for r in results:
        for k in r["head"]["judge_scores"]:
            if k not in judge_names:
                judge_names.append(k)
    out: dict[str, Any] = {"pairwise_position_consistency": pw.get("position_consistency")}
    if len(judge_names) >= 2:
        matrix = [[r["head"]["judge_scores"].get(j) for r in results] for j in judge_names]
        out["judge_panel"] = judge_names
        out["krippendorff_alpha"] = krippendorff_alpha_interval(matrix)
    trial_var = []
    for r in results:
        scores = [np.mean([j["score"] for j in t["judges"]]) for t in r["head"]["trials"] if t["judges"]]
        if len(scores) > 1:
            trial_var.append(float(np.std(scores)))
    if trial_var:
        out["mean_trial_score_std"] = float(np.mean(trial_var))
    return out


def _cost(results: list[dict], prices: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for side in ("base", "head"):
        trs = [Transcript.from_dict(t["transcript"]) for r in results if r[side] for t in r[side]["trials"]]
        if not trs:
            continue
        out[side] = {
            "input_tokens": sum(t.input_tokens for t in trs),
            "output_tokens": sum(t.output_tokens for t in trs),
            "usd": round(sum(transcript_cost(t, prices) for t in trs), 6),
        }
    out["run_usd"] = USAGE.snapshot()["cost_usd"]
    return out


def _latency(results: list[dict]) -> dict[str, Any]:
    out = {}
    for side in ("base", "head"):
        vals = [
            t["transcript"]["latency_ms"]
            for r in results
            if r[side]
            for t in r[side]["trials"]
            if not t["transcript"].get("cached")
        ]
        if vals:
            out[side] = {"p50_ms": _percentile(vals, 50), "p95_ms": _percentile(vals, 95), "n": len(vals)}
    return out


def _behavior_summary(results: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in results:
        for b in r["case"].get("behaviors", []):
            e = out.setdefault(b, {"cases": 0, "statuses": {}, "head_pass": 0})
            e["cases"] += 1
            e["statuses"][r["status"]] = e["statuses"].get(r["status"], 0) + 1
            if r["status"] in ("PASS", "IMPROVED"):
                e["head_pass"] += 1
    return out


def _absolute_verdict(counts: dict[str, int]) -> tuple[str, list[dict[str, Any]]]:
    trace = [
        {"level": "fail", "expr": "fail_cases > 0", "triggered": counts["fail_cases"] > 0},
        {"level": "warn", "expr": "warn_cases > 0", "triggered": counts["warn_cases"] > 0},
    ]
    if counts["fail_cases"] > 0:
        return "FAIL", trace
    if counts["warn_cases"] > 0:
        return "WARN", trace
    return "PASS", trace
