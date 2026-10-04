from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from gitgrounded.cases.model import Case
from gitgrounded.config.schema import CoverageCfg
from gitgrounded.coverage.dimensions import build_dimensions
from gitgrounded.coverage.diversity import select_diverse
from gitgrounded.coverage.extract import Behavior, extract_behaviors
from gitgrounded.coverage.ingest import ingest
from gitgrounded.coverage.logs import analyze_logs
from gitgrounded.coverage.metrics import compute_coverage
from gitgrounded.coverage.minimize import greedy_minimize
from gitgrounded.coverage.mutate import Mutant, generate_mutants
from gitgrounded.coverage.planner import BehaviorPlan, Cell, plan
from gitgrounded.coverage.suite_store import SuiteStore, seal
from gitgrounded.coverage.synthesize import synthesize_for_behavior
from gitgrounded.coverage.validate import validate_cases
from gitgrounded.engine import Engine, RunOptions
from gitgrounded.errors import ConfigError
from gitgrounded.providers.embeddings import build_embedder
from gitgrounded.sources.variant import Variant, derive_variant, diff_text, materialize


class CoveragePipeline:
    def __init__(self, engine: Engine, suite_name: str | None, log: Callable[[str], None] | None = None):
        self.engine = engine
        self.suite_name, self.suite = engine.cfg.suite(suite_name)
        self.cfg: CoverageCfg = engine.cfg.coverage_for(self.suite_name)
        self.project = engine.project
        self.cache = engine.cache
        self.store = SuiteStore(self.project, self.suite_name)
        self.embedder = build_embedder(engine.cfg.providers.embeddings)
        self.generator = engine.cfg.providers.generator
        self.validator = engine.cfg.providers.validator or engine.cfg.providers.judge
        self.log = log or (lambda m: None)
        self.target_cfg = engine.cfg.target(self.suite.target)
        self._fill_sources()

    def _fill_sources(self) -> None:
        src = self.cfg.sources
        if not src.system_prompt and getattr(self.target_cfg, "system_prompt_file", None):
            src.system_prompt = self.target_cfg.system_prompt_file
        if not src.tools and getattr(self.target_cfg, "tools_file", None):
            src.tools = [self.target_cfg.tools_file]
        if not self.cfg.mutation.target_file:
            self.cfg.mutation.target_file = src.system_prompt

    def discover(self, files: dict[str, str] | None = None) -> dict[str, Any]:
        system_text = getattr(self.target_cfg, "system_prompt", None)
        sentences = ingest(self.project, self.cfg.sources, files, system_text)
        if not sentences:
            raise ConfigError(
                f"suite '{self.suite_name}' has no coverage sources; set suites.{self.suite_name}.coverage.sources.system_prompt (and documents/tools)"
            )
        self.log(f"extracting behaviors from {len(sentences)} source sentences")
        behaviors = extract_behaviors(self.generator, self.cache, sentences, self.embedder)
        dims = build_dimensions(self.cfg)
        proposed = self._propose_dimensions(sentences, dims) if self.cfg.propose_dimensions else {}
        if self.cfg.apply_proposed_dimensions:
            for k, v in proposed.items():
                dims.setdefault(k, v)
        return {"sentences": sentences, "behaviors": behaviors, "dimensions": dims, "proposed_dimensions": proposed}

    def _propose_dimensions(self, sentences, dims: dict[str, list[str]]) -> dict[str, list[str]]:
        import json as _json

        from gitgrounded.providers.base import build_provider
        from gitgrounded.providers.llm import complete_json

        system = """You design test conditions for an AI application. Given its instructions, propose up to 3 extra dimensions along which real user inputs vary for THIS app (for example user expertise, plan tier, product line, channel), each with 2 to 5 short values. Do not repeat existing dimensions.
Return JSON: {"dimensions": {"name": ["value", ...]}}"""
        payload = {
            "instructions": " ".join(s.text for s in sentences if s.kind == "prompt")[:8000],
            "existing": list(dims),
        }
        key = self.cache.key("dims", self.generator.model_dump(mode="json"), payload)
        hit = self.cache.get("coverage", key)
        if hit is None:
            data, _ = complete_json(
                build_provider(self.generator), system, _json.dumps(payload), task="propose_dimensions", meta=payload
            )
            raw = data.get("dimensions", {}) if isinstance(data, dict) else {}
            hit = {
                str(k): [str(x) for x in v][:5]
                for k, v in raw.items()
                if isinstance(v, list) and len(v) >= 2 and k not in dims
            }
            self.cache.set("coverage", key, hit)
        return dict(list(hit.items())[:3])

    def _examples(self) -> list[str]:
        out = [c.input_text() for c in self.store.cases() if c.origin in ("human", "log")][:6]
        if self.suite.cases:
            try:
                cases, _ = self.engine.load_suite_cases(self.suite_name, self.suite)
                out += [c.input_text() for c in cases[:6]]
            except ConfigError:
                pass
        return out

    def synth(self, incremental: bool = True, use_logs: bool = True) -> dict[str, Any]:
        found = self.discover()
        behaviors: list[Behavior] = found["behaviors"]
        dims = found["dimensions"]
        plans = plan(behaviors, dims, self.cfg)
        plan_by_id = {p.behavior_id: p for p in plans}
        keep: list[Case] = []
        regenerate = list(behaviors)
        if incremental and self.store.exists():
            old = {b.id: b for b in self.store.behaviors()}
            old_cases = self.store.cases()
            unchanged = {b.id for b in behaviors if b.id in old and old[b.id].fingerprint() == b.fingerprint()}
            keep = [c for c in old_cases if (c.behaviors and set(c.behaviors) <= unchanged) or c.origin == "human"]
            regenerate = [b for b in behaviors if b.id not in unchanged]
            self.log(
                f"incremental: keeping {len(keep)} cases for {len(unchanged)} unchanged behaviors, regenerating {len(regenerate)}"
            )
        examples = self._examples()
        existing = [c.input_text() for c in keep]
        self.log(f"synthesizing cases for {len(regenerate)} behaviors")

        def work(b: Behavior) -> list[Case]:
            return synthesize_for_behavior(self.generator, self.cache, b, plan_by_id[b.id], examples, list(existing))

        with ThreadPoolExecutor(max_workers=max(1, min(8, self.engine.cfg.execution.max_concurrency))) as pool:
            generated = [c for group in pool.map(work, regenerate) for c in group]
        self.log(f"validating {len(generated)} candidate cases")
        by_id = {b.id: b for b in behaviors}
        valid, dropped = validate_cases(self.validator, self.cache, generated, by_id)
        groups: dict[str, list[Case]] = {}
        for c in valid:
            groups.setdefault(c.behaviors[0], []).append(c)
        targets = {p.behavior_id: p.target_cases for p in plans}
        selected, div_stats = select_diverse(groups, targets, self.embedder, self.cfg.diversity_lambda)
        log_report = None
        log_cases: list[Case] = []
        if use_logs and self.cfg.sources.logs:
            path = self.project.resolve(self.cfg.sources.logs)
            if path.exists():
                self.log(f"analyzing logs {self.cfg.sources.logs}")
                analysis = analyze_logs(path, behaviors, self.embedder, self.generator, self.cache)
                log_cases = analysis.pop("cases")
                log_report = analysis
        keep_ids = {c.id for c in keep}
        final = keep + [c for c in selected if c.id not in keep_ids] + [c for c in log_cases if c.id not in keep_ids]
        coverage = compute_coverage(
            behaviors,
            {p.behavior_id: p.to_dict() for p in plans},
            final,
            self.cfg.strength,
            self.cfg.min_cases_per_behavior,
            diversity=div_stats,
            logs=log_report,
        )
        version = self.store.save(
            behaviors,
            dims,
            [p.to_dict() for p in plans],
            final,
            coverage,
            dropped,
            extra={"generator": self.generator.model, "validator": self.validator.model, "strength": self.cfg.strength},
            logs=log_report,
        )
        seal(self.store)
        return {
            "version": version,
            "behaviors": len(behaviors),
            "cases": len(final),
            "dropped": len(dropped),
            "coverage": coverage["summary"],
            "path": str(self.store.path("current.jsonl")),
        }

    def _variant_files(self, variant: Variant) -> dict[str, str]:
        files = dict(variant.files)
        rels = [
            self.cfg.sources.system_prompt,
            self.cfg.mutation.model_file,
            *self.cfg.sources.documents,
            *self.cfg.sources.tools,
        ]
        for rel in rels:
            if rel and rel not in files:
                p = variant.root / rel
                if p.exists():
                    files[rel] = p.read_text(encoding="utf-8", errors="replace")
        return files

    def mutate(self, ref: str = "@worktree", repair: bool = True, max_mutants: int | None = None) -> dict[str, Any]:
        if not self.store.exists():
            raise ConfigError(
                f"suite '{self.suite_name}' has no synthesized cases yet; run `gitgrounded synth --suite {self.suite_name}`"
            )
        cases = self.store.cases()
        behaviors = self.store.behaviors()
        watch = self.engine.watch_paths(self.suite)
        base = materialize(self.project, ref, watch)
        files = self._variant_files(base)
        mcfg = self.cfg.mutation.model_copy(update={"max_mutants": max_mutants or self.cfg.mutation.max_mutants})
        mutants = generate_mutants(mcfg, behaviors, files, self.cfg.mutation.target_file)
        if not mutants:
            raise ConfigError(
                "no mutants could be generated; check coverage.mutation.target_file and that behaviors cite it"
            )
        target = self.engine.target(self.suite.target)
        copy_tree = target.kind in ("python", "agent", "mcp")
        self.log(f"running {len(cases)} cases against {len(mutants)} mutants")
        results = []
        kills: dict[str, set[str]] = {c.id: set() for c in cases}
        added: list[Case] = []
        for m in mutants:
            res = self._run_mutant(base, m, cases, copy_tree)
            for cid in res["killing_cases"]:
                kills.setdefault(cid, set()).add(m.id)
            results.append(res)
            self.log(f"{m.id}: {'killed' if res['killed'] else 'survived'} ({len(res['killing_cases'])} cases)")
        if repair and self.cfg.mutation.repair_rounds > 0:
            by_id = {b.id: b for b in behaviors}
            for res in results:
                if res["killed"] or res["operator"] == "model_downgrade":
                    continue
                m = next(x for x in mutants if x.id == res["id"])
                new_cases = self._repair(base, m, by_id, cases + added, copy_tree)
                if new_cases:
                    killing = self._run_mutant(base, m, new_cases, copy_tree)["killing_cases"]
                    keepers = [c for c in new_cases if c.id in killing]
                    if keepers:
                        added += keepers
                        res["killed"] = True
                        res["killing_cases"] = sorted(set(res["killing_cases"]) | {c.id for c in keepers})
                        res["repaired"] = True
                        for c in keepers:
                            kills.setdefault(c.id, set()).add(m.id)
                        self.log(f"{m.id}: repaired with {len(keepers)} new cases")
        all_cases = cases + added
        self._mark_equivalent(results, files)
        scored = [r for r in results if not r.get("equivalent")]
        killed = sum(1 for r in scored if r["killed"])
        score = killed / len(scored) if scored else None
        minimal_ids = greedy_minimize(all_cases, kills, self.cfg.min_cases_per_behavior)
        minimal = [c for c in all_cases if c.id in set(minimal_ids)]
        mutation = {
            "ref": ref,
            "score": score,
            "killed": killed,
            "total": len(scored),
            "equivalent": len(results) - len(scored),
            "target": self.cfg.mutation_target,
            "meets_target": score is not None and score >= self.cfg.mutation_target,
            "mutants": results,
            "added_cases": [c.id for c in added],
            "minimal_cases": len(minimal),
        }
        if added:
            self.store.write_cases(all_cases)
        self.store.write_cases(minimal, minimal=True)
        self.store.write_json("mutation.json", mutation)
        plans_data = self.store.read_json("plan.json", {"plans": []}).get("plans", [])
        coverage = compute_coverage(
            behaviors,
            {p["behavior_id"]: p for p in plans_data},
            all_cases,
            self.cfg.strength,
            self.cfg.min_cases_per_behavior,
            mutation=mutation,
            logs=self.store.read_json("logs.json"),
        )
        self.store.write_json("coverage.json", coverage)
        meta = self.store.meta()
        meta["mutation_score"] = score
        self.store.write_json("suite.json", meta)
        seal(self.store)
        self.store.snapshot()
        return mutation

    def _mark_equivalent(self, results: list[dict[str, Any]], files: dict[str, str]) -> None:
        import json as _json

        from gitgrounded.providers.base import build_provider
        from gitgrounded.providers.llm import complete_json

        system = """A test suite failed to detect a deliberate change to an AI application's instructions. Decide whether the change is EQUIVALENT, meaning it cannot change any correct response (for example rewording with identical meaning, or deleting a sentence that another sentence already states).
Return JSON: {"equivalent": true or false, "reason": "..."}"""
        for r in results:
            if r["killed"] or r["operator"] == "model_downgrade":
                continue
            payload = {"change": r["description"], "hint": r.get("diff_hint", "")[:2000]}
            key = self.cache.key("equiv", self.validator.model_dump(mode="json"), payload)
            hit = self.cache.get("coverage", key)
            if hit is None:
                data, _ = complete_json(
                    build_provider(self.validator), system, _json.dumps(payload), task="equivalent_mutant", meta=payload
                )
                hit = (
                    {"equivalent": bool(data.get("equivalent")), "reason": str(data.get("reason", ""))[:300]}
                    if isinstance(data, dict)
                    else {"equivalent": False, "reason": ""}
                )
                self.cache.set("coverage", key, hit)
            r["equivalent"] = hit["equivalent"]
            r["equivalent_reason"] = hit["reason"]

    def _run_mutant(self, base: Variant, m: Mutant, cases: list[Case], copy_tree: bool) -> dict[str, Any]:
        mv = derive_variant(self.project, base, f"mutant:{m.id}", m.overrides, m.overlay, copy_tree=copy_tree)
        diff = diff_text(self.project, base, mv, list(m.overrides))
        result = self.engine.run_variants(
            self.suite_name,
            base,
            mv,
            diff,
            RunOptions(write=False, generate=False, trials=1),
            mode="mutant",
            cases=cases,
        )
        killing = [r["case"]["id"] for r in result.cases if r["status"] in ("FAIL", "WARN")]
        return {
            **m.to_dict(),
            "killed": result.verdict in ("FAIL", "WARN"),
            "verdict": result.verdict,
            "killing_cases": killing,
            "delta_score": (result.metrics.get("score", {}).get("delta") or {}).get("mean"),
        }

    def _repair(
        self, base: Variant, m: Mutant, behaviors: dict[str, Behavior], existing: list[Case], copy_tree: bool
    ) -> list[Case]:
        out: list[Case] = []
        for bid in m.behavior_ids[:3]:
            b = behaviors.get(bid)
            if b is None:
                continue
            bplan = BehaviorPlan(bid, 3, {}, [Cell(bid, i, {"difficulty": "edge"}) for i in range(3)])
            start = sum(1 for c in existing + out if c.behaviors and c.behaviors[0] == bid) + 100
            cands = synthesize_for_behavior(
                self.generator,
                self.cache,
                b,
                bplan,
                [],
                [c.input_text() for c in existing],
                hint=f"Write inputs where this exact change would produce a different, worse answer: {m.diff_hint}",
                start_index=start,
            )
            valid, _ = validate_cases(self.validator, self.cache, cands, behaviors)
            for c in valid:
                c.tags.append("mutation_repair")
            out += valid
        return out
