# GitGrounded v2: commit plan, test plan and remaining work

This file turns the single `v2/rebuild` commit into 24 small, reviewable commits, says exactly how to test each one, then lists real world tests to run with API keys, and finally everything still left from `docs/ROADMAP.md`.

# Part 1. Recreate the work as 24 commits

## 1.0 Setup

Use the unzipped repo (it already contains branch `v2/rebuild`):

```bash
cd ~/gg-v2/gitgrounded
git branch --show-current
git log --oneline -2
```

Or pull the branch into your existing clone:

```bash
cd ~/path/to/your/gitgrounded
git fetch ~/gg-v2/gitgrounded v2/rebuild:v2/rebuild
```

Start a clean branch from the old `main` commit and pull files over one commit at a time:

```bash
git checkout -b v2/split fc538cd
export GITGROUNDED_OFFLINE=1
alias take='git checkout v2/rebuild --'
```

Each commit below is: `take` the files, `git rm` the old ones, run the test, commit. When you reach commit 24 the trees must be identical:

```bash
git diff v2/rebuild v2/split --stat
```

Empty output means done. Then push `v2/split` (or rename it to `v2`) and open a pull request.

## Commit 1. chore: clean repo, fix gitignore and issue templates

```bash
git rm -q GitGrounded_Hackathon_One_Pager.pdf GitGrounded_Hackathon_One_Pager.pptx report_test_drop-citation-rule.json report_test_model-downgrade.json report_test_safe-wording-tweak.json demo.sh dashboard.py
git mv .github/workflows/ISSUE_TEMPLATE .github/ISSUE_TEMPLATE
take .gitignore .env.example .dockerignore
git add -A
git commit -m "chore: remove binaries and stale reports, fix gitignore, move issue templates"
```

Test:

```bash
git status --short
ls .github/ISSUE_TEMPLATE
```

Expected: clean tree, three template files listed. After push, GitHub "New issue" shows the bug and feature templates.

## Commit 2. build: src layout and package core

```bash
git rm -rq gitgrounded gitgrounded.py requirements.txt tests
take pyproject.toml src/gitgrounded/__init__.py src/gitgrounded/__main__.py src/gitgrounded/errors.py src/gitgrounded/project.py src/gitgrounded/canonical.py src/gitgrounded/jsonpath.py
take src/gitgrounded/assertions/__init__.py src/gitgrounded/cases/__init__.py src/gitgrounded/cli/__init__.py src/gitgrounded/config/__init__.py src/gitgrounded/coverage/__init__.py src/gitgrounded/evidence/__init__.py src/gitgrounded/exec/__init__.py src/gitgrounded/judges/__init__.py src/gitgrounded/mcp/__init__.py src/gitgrounded/providers/__init__.py src/gitgrounded/report/__init__.py src/gitgrounded/sources/__init__.py src/gitgrounded/stats/__init__.py src/gitgrounded/store/__init__.py src/gitgrounded/targets/__init__.py
git add -A
git commit -m "build: move to src layout with project root discovery and canonical JSON"
```

Test:

```bash
pip install -e ".[dev,mcp]"
python -c "from gitgrounded.project import find_project; p = find_project(); print(p.root, p.state_dir)"
python -c "from gitgrounded.canonical import content_hash; print(content_hash({'b': 1, 'a': 2}) == content_hash({'a': 2, 'b': 1}))"
python -c "from gitgrounded.jsonpath import jsonpath_get; print(jsonpath_get({'a': [{'b': 3}]}, '$.a[0].b'))"
```

Expected: your repo root and `<root>/.gitgrounded`, then `True`, then `3`. The `gitgrounded` command will not work until commit 19; that is expected.

## Commit 3. feat(config): typed gitgrounded.yml v1

```bash
take src/gitgrounded/config/schema.py src/gitgrounded/config/loader.py src/gitgrounded/config/defaults.yaml
git add -A
git commit -m "feat(config): typed gitgrounded.yml v1 with env interpolation and defaults"
```

Test:

```bash
python -c "from gitgrounded.config.loader import parse_config; c = parse_config({}); print(c.providers.judge.model)"
python -c "from gitgrounded.config.loader import parse_config; parse_config({'targets': {'t': {'type': 'python'}}})"
```

Expected: `claude-sonnet-4-6`, then a `ConfigError` naming `targets.t.python.entry` as missing.

## Commit 4. feat(providers): LLM providers, offline mode, usage and budget

```bash
take src/gitgrounded/providers src/gitgrounded/stats/cost.py tests/__init__.py tests/conftest.py tests/test_config.py
git add -A
git commit -m "feat(providers): anthropic, openai compatible, ollama and offline providers with usage tracking"
```

Test:

```bash
pytest -q tests/test_config.py
python -c "
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.providers.base import build_provider
p = build_provider(ProviderCfg(provider='anthropic', model='x'))
print(type(p).__name__, p.complete('Always cite the policy.', [{'role': 'user', 'content': 'refund?'}]).text)
"
```

Expected: 7 passed, then `MockProvider` and a short mock answer (offline mode replaces every provider with the mock).

Real key check (optional, costs a fraction of a cent):

```bash
GITGROUNDED_OFFLINE=0 python -c "
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.providers.base import build_provider
print(build_provider(ProviderCfg(provider='groq', model='openai/gpt-oss-20b')).complete('', [{'role': 'user', 'content': 'say ok'}]).text)
"
```

## Commit 5. feat(cases): case model, loaders, diff targeted generation, cache and history

```bash
take src/gitgrounded/cases src/gitgrounded/store
git add -A
git commit -m "feat(cases): JSONL case model with expectations, content addressed cache and endpoint history"
```

Test:

```bash
take examples/triage/data/cases.jsonl
python -c "
from pathlib import Path
from gitgrounded.cases.loader import load_cases
from gitgrounded.cases.model import dataset_hash
c = load_cases(Path('examples/triage/data/cases.jsonl')); print(len(c), c[0].expectations[0].text[:30], dataset_hash(c)[:12])
"
git reset -q examples && rm -rf examples/triage/data/cases.jsonl
```

Expected: `10`, an expectation snippet and a stable hash.

## Commit 6. feat(sources): git worktree variants and working tree mode

```bash
take src/gitgrounded/sources/variant.py
git add -A
git commit -m "feat(sources): materialize git refs as worktrees, support @worktree and derived variants"
```

Test:

```bash
python -c "
from gitgrounded.project import find_project
from gitgrounded.sources.variant import materialize, diff_text
p = find_project()
a = materialize(p, 'baseline', ['prompts/triage.txt']); b = materialize(p, 'test/drop-citation-rule', ['prompts/triage.txt'])
print(a.sha[:8], b.sha[:8], a.root)
print(diff_text(p, a, b, ['prompts/triage.txt']))
"
git worktree list
```

Expected: two short SHAs, a worktree path under `.gitgrounded/worktrees/`, and a diff that swaps "Always cite the exact policy line" for "Keep your answer as short as possible". The old demo branches still exist in your repo, so this works here.

## Commit 7. feat(targets): python, http, openai chat and MCP targets

```bash
take src/gitgrounded/targets src/gitgrounded/mcp/introspect.py
git add -A
git commit -m "feat(targets): isolated python worker, http json, openai chat and MCP stdio/http targets"
```

Test (python target in its own process):

```bash
mkdir -p /tmp/tgt && printf 'def run(x, ctx):\n    return {"output": x.upper(), "usage": {"input_tokens": 3}}\n' > /tmp/tgt/app.py
python -c "
from pathlib import Path
from gitgrounded.cases.model import Case
from gitgrounded.config.schema import PythonTarget as Cfg
from gitgrounded.sources.variant import Variant
from gitgrounded.targets.python_callable import PythonTarget
t = PythonTarget('t', Cfg(type='python', entry='app:run'))
v = Variant('v', Path('/tmp/tgt'), {}, 'h')
print(t.invoke(Case(id='c', input='hello'), v, 0).output); t.close()
"
```

Expected: `HELLO`.

## Commit 8. feat(stats): intervals, significance, reliability, ranking

```bash
take src/gitgrounded/stats tests/test_stats.py
git add -A
git commit -m "feat(stats): bootstrap and Wilson intervals, paired permutation tests, Holm, agreement metrics, ranking"
```

Test: `pytest -q tests/test_stats.py` gives 7 passed.

## Commit 9. feat(assertions): deterministic checks

```bash
take src/gitgrounded/assertions tests/test_assertions.py
git add -A
git commit -m "feat(assertions): 20 deterministic assertions with plugin entry points"
```

Test: `pytest -q tests/test_assertions.py` gives 6 passed.

## Commit 10. feat(judges): rubric, pairwise and calibration

```bash
take src/gitgrounded/judges
git add -A
git commit -m "feat(judges): YAML rubrics, order swapped pairwise judge, human label calibration"
```

Test:

```bash
python -c "from gitgrounded.judges.rubric import load_rubric; [print(n, load_rubric(n).dimension_names) for n in ['grounded_answer','instruction_following','format','helpfulness','safety_refusal','tool_use']]"
```

Expected: six rubrics with their dimensions.

## Commit 11. feat(gates): verdict rules

```bash
take src/gitgrounded/gates.py tests/test_gates.py
git add -A
git commit -m "feat(gates): safe expression language for PASS, WARN and FAIL with a decision trace"
```

Test: `pytest -q tests/test_gates.py` gives 5 passed.

## Commit 12. feat(engine): executor, run engine and triage example

```bash
take src/gitgrounded/exec src/gitgrounded/engine.py src/gitgrounded/report/model.py examples/triage tests/test_engine_e2e.py
git rm -rq app config data prompts
git add -A
git commit -m "feat(engine): run cases on base and head, evaluate, aggregate stats and gate; move triage demo to examples"
```

Test:

```bash
pytest -q tests/test_engine_e2e.py -k "scenarios or downgrade or cache"
```

Expected: 5 passed (safe tweak PASS, citation drop FAIL, model downgrade FAIL, downgrade causes new assertion failures, second run fully cached). The bundle and report tests in this file pass after commits 13, 14 and 19.

## Commit 13. feat(report): terminal, HTML, Markdown, JUnit

```bash
take src/gitgrounded/report
git add -A
git commit -m "feat(report): rich terminal view, self contained HTML with word diffs, PR Markdown, JUnit XML"
```

Test:

```bash
pytest -q tests/test_engine_e2e.py -k reports
```

Expected: 1 passed.

## Commit 14. feat(evidence): Merkle, bundles, signing, verification

```bash
take src/gitgrounded/evidence tests/test_canonical_merkle.py
git add -A
git commit -m "feat(evidence): canonical records, Merkle root, deterministic .ggb bundles, Ed25519 and Sigstore signing, verify"
```

Test: `pytest -q tests/test_canonical_merkle.py` gives 5 passed.

## Commit 15. feat(coverage): ingest, behavior extraction, dimensions, covering arrays

```bash
take src/gitgrounded/coverage/ingest.py src/gitgrounded/coverage/extract.py src/gitgrounded/coverage/dimensions.py src/gitgrounded/coverage/planner.py tests/test_planner.py
git add -A
git commit -m "feat(coverage): traceable behavior extraction and pairwise covering array planner"
```

Test: `pytest -q tests/test_planner.py` gives 5 passed. The hypothesis test proves every pair of conditions is covered for random dimension shapes.

## Commit 16. feat(coverage): synthesis, validation, diversity, logs, suite store

```bash
take src/gitgrounded/coverage/synthesize.py src/gitgrounded/coverage/validate.py src/gitgrounded/coverage/diversity.py src/gitgrounded/coverage/metrics.py src/gitgrounded/coverage/suite_store.py src/gitgrounded/coverage/logs.py
git add -A
git commit -m "feat(coverage): case synthesis with oracles, validator, MMR diversity, log clustering, versioned suites"
```

Test:

```bash
python -c "
from gitgrounded.coverage.diversity import remove_near_duplicates
from gitgrounded.cases.model import Case
cs = [Case(id=str(i), input='Can I get a refund for a double charge?' + ('!' if i % 2 else '')) for i in range(6)] + [Case(id='x', input='My parcel is late')]
kept, removed = remove_near_duplicates(cs); print(len(kept), len(removed))
"
python -c "from gitgrounded.coverage.logs import redact; print(redact('mail me at a@b.com or 9876543210, PAN ABCDE1234F'))"
```

Expected: `2 5`, then the text with `[email]`, `[phone]`, `[pan]`.

## Commit 17. feat(coverage): mutation testing, minimization, pipeline, review UI

```bash
take src/gitgrounded/coverage/mutate.py src/gitgrounded/coverage/minimize.py src/gitgrounded/coverage/pipeline.py src/gitgrounded/coverage/review_server.py tests/test_mutate_ops.py tests/test_coverage_pipeline.py
git add -A
git commit -m "feat(coverage): prompt mutation testing with repair, minimal CI suite, end to end pipeline, review UI"
```

Test:

```bash
pytest -q tests/test_mutate_ops.py tests/test_coverage_pipeline.py
```

Expected: 4 passed.

## Commit 18. feat(mcp): schema diff, MCP server mode, weather example

```bash
take src/gitgrounded/mcp/schema_diff.py src/gitgrounded/mcp/server.py examples/mcp_weather tests/test_schema_diff.py
git add -A
git commit -m "feat(mcp): tool schema diff with semver suggestion, GitGrounded MCP server, weather example"
```

Test: `pytest -q tests/test_schema_diff.py` gives 5 passed.

## Commit 19. feat(cli): subcommand CLI with legacy flag support

```bash
take src/gitgrounded/cli tests/test_cli.py tests/test_http_check.py
git add -A
git commit -m "feat(cli): run, check, rank, history, discover, synth, mutate, suite, report, bundle, verify, calibrate, mcp, init"
```

Test: the whole suite now passes.

```bash
pytest -q
gitgrounded --version
gitgrounded --help
```

Expected: 58 passed.

## Commit 20. feat(examples): standalone endpoint bots

```bash
take examples/endpoint_bots
git rm -rq servers
git add -A
git commit -m "feat(examples): endpoint bots example without importing gitgrounded internals"
```

Test:

```bash
pip install flask
cd examples/endpoint_bots && (python chatbots.py &) && sleep 1
gitgrounded check
echo "Keep every answer under 5 words." > prompts/ai-chatbot2.txt
gitgrounded check
git checkout prompts/ai-chatbot2.txt && pkill -f chatbots.py; cd ../..
```

Expected: the first check stores baselines for three bots, the second shows a regression only for `bot2`.

## Commit 21. feat(verifier): browser verifier

```bash
take verifier/index.html
git add -A
git commit -m "feat(verifier): client side bundle verifier with Merkle and Ed25519 checks"
```

Test: see Part 2, test T7.

## Commit 22. ci: tests matrix, publish pipeline, dogfood, GitHub Action

```bash
git rm -q .github/workflows/workflow.yml
take .github/workflows/tests.yml .github/workflows/publish.yml .github/workflows/gitgrounded.yml action/action.yml
git add -A
git commit -m "ci: OS and Python matrix, wheel smoke tests before publishing, composite GitHub Action with signing and attestation"
```

Test: push the branch and open a pull request. Expected: Tests workflow green on 9 jobs plus lint; the dogfood workflow runs, uploads an artifact named `gitgrounded-<run id>` and posts one comment that gets updated (not duplicated) on the next push.

## Commit 23. build: Docker, pre commit hooks, GitLab template

```bash
take Dockerfile .pre-commit-hooks.yaml ci/gitlab-ci.yml
git add -A
git commit -m "build: Docker image, pre commit hooks and GitLab CI template"
```

Test:

```bash
docker build -t gitgrounded:dev .
docker run --rm gitgrounded:dev --version
```

## Commit 24. docs: README, coverage, evidence, roadmap, changelog

```bash
take README.md CHANGELOG.md CONTRIBUTING.md CITATION.cff BUILD_STATUS.md docs
git add -A
git commit -m "docs: new README, coverage and evidence guides, roadmap, changelog for 0.2.0"
git diff v2/rebuild v2/split --stat
```

Expected: the final diff is empty.

# Part 2. What to test with real models

Run these in the demo repo with real keys. Each test lists what proves it works and what to look at when it does not.

```bash
python examples/triage/make_demo_repo.py /tmp/demo && cd /tmp/demo
unset GITGROUNDED_OFFLINE
export ANTHROPIC_API_KEY=... GROQ_API_KEY=...
```

## T1. Change detection, real judge

```bash
gitgrounded run --base baseline --head test/safe-wording-tweak --open
gitgrounded run --base baseline --head test/drop-citation-rule --open
gitgrounded run --base baseline --head test/model-downgrade --open
```

Pass if: safe tweak is PASS or WARN with delta CI crossing 0; citation drop is FAIL with `policy_line` empty or wrong in the head outputs; model downgrade shows score or assertion differences. Look at the HTML: word diffs, judge reasons, gate table.
If wrong: read `judge` reasons in the case drawer; tune `src/gitgrounded/judges/rubrics/grounded_answer.yaml` anchors or the pairwise prompt in `judges/pairwise.py`.

## T2. Noise floor (most important for credibility)

```bash
gitgrounded run --base baseline --head baseline --trials 3 --no-generate
```

Pass if: verdict PASS, every delta CI contains 0, `unstable_cases` small. If baseline vs itself fails, the gates are too sensitive: raise `FAIL_DROP` and `WARN_DROP` in `engine.py` or gate on `delta.score.ci_upper < 0`.

## T3. Trials and statistics

```bash
gitgrounded run --base baseline --head test/drop-citation-rule --trials 3 --format json | python -m json.tool | head -80
```

Pass if: `metrics.score.delta.p_adjusted` below 0.05 and CI fully below 0; `reliability.pairwise_position_consistency` above 0.8.

## T4. Diff targeted generation

```bash
gitgrounded run --base baseline --head test/drop-citation-rule
```

Pass if: 6 `diff-00N` cases appear, all about citing policy lines, none duplicating seed questions.

## T5. Coverage engine on the triage prompt

```bash
gitgrounded discover --suite auto
gitgrounded synth --suite auto
gitgrounded suite review --suite auto
gitgrounded mutate --suite auto
gitgrounded suite coverage --suite auto --open
```

Pass if:
* Discover lists the citation rule, the "do not invent" rule, the JSON format rule, one knowledge behavior per policy line and 2 to 4 implicit behaviors. Write down every rule you see in the prompt in 10 minutes first and compare; missing ones mean `EXTRACT_SYSTEM` in `coverage/extract.py` needs work.
* Synth gives cases in angry, typo heavy and Hinglish styles that read like real users, and `dropped.json` shows the validator removed some bad ones.
* Mutation score is meaningful (target 0.85). Deleting the citation rule must be detected. Surviving mutants that are real behavior changes point to missing cases; survivors that change nothing are equivalent mutants.
* Review UI: 50 cases in under 5 minutes with j, k, a, r, s keys.
Cost check: `cat .gitgrounded/runs/*/result.json | grep run_usd` and the console cost line.

## T6. Evidence bundle, local signing

```bash
gitgrounded run --base baseline --head test/drop-citation-rule --bundle
B=$(ls -t .gitgrounded/runs/*/evidence.ggb | head -1)
gitgrounded verify "$B" -v
cp "$B" /tmp/t.ggb && python - <<'EOF'
import zipfile
src, dst = "/tmp/t.ggb", "/tmp/bad.ggb"
with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w") as zo:
    for i in zi.infolist():
        d = zi.read(i)
        if i.filename == "summary.json":
            d = d.replace(b'"verdict":"FAIL"', b'"verdict":"PASS"')
        zo.writestr(i, d)
EOF
gitgrounded verify /tmp/bad.ggb
```

Pass if: first verify says `VERIFIED_SELF_SIGNED`, the edited copy says `TAMPERED` and names `summary.json`.

## T7. Browser verifier

```bash
cd ~/gg-v2/gitgrounded/verifier && python -m http.server 8080
```

Open `http://localhost:8080`, drop the good bundle, then `/tmp/bad.ggb`. Pass if: first shows VERIFIED (SELF SIGNED) and "Open the report" works; second shows TAMPERED. Test Chrome, Firefox and Safari (Ed25519 in WebCrypto needs recent versions).

## T8. Sigstore signing and attestation in GitHub Actions

Push the branch, open a pull request that edits `examples/triage/prompts/triage.txt`. In the dogfood workflow set `sign: sigstore` once. Download the artifact, then:

```bash
pip install "gitgrounded[sign]"
gitgrounded verify evidence.ggb --identity "https://github.com/amareshhebbar/gitgrounded/.github/workflows/gitgrounded.yml@refs/pull/<N>/merge"
gh attestation verify evidence.ggb --repo amareshhebbar/gitgrounded
```

Pass if: both succeed. If the identity string fails, run `gitgrounded verify evidence.ggb` without `--identity`; it prints the certificate SAN to copy.

## T9. Live endpoint history

Commit 20 test with real Groq answers instead of offline. Pass if: unchanged prompts give PASS run after run (this is also a noise floor test for live APIs), the 5 word prompt gives FAIL.

## T10. MCP

```bash
cd examples/mcp_weather
git init -q && git add -A && git commit -qm v1
sed -i 's/Get the weather forecast for a city for the next N days./Weather data./' descriptions.json
gitgrounded mcp diff --base HEAD
gitgrounded run --base HEAD
```

Pass if: diff says risky description change, minor bump; the run with a real agent model shows whether tool selection actually got worse. Also test `gitgrounded mcp serve` from Claude Code or Cursor by adding it as an MCP server and asking it to run the suite.

## T11. Your own project

Pick one real prompt (FuelPilot coach prompt or a ClinicalSearch agent), `gitgrounded init`, point a target at it, run T5 and T1 on a real change. This is the test that matters most before launch; note every friction point in setup.

## T12. Packaging

```bash
python -m build && twine check dist/*
python -m venv /tmp/v && /tmp/v/bin/pip install dist/*.whl
cd /tmp && /tmp/v/bin/gitgrounded --version
```

Then tag `v0.2.0rc1` and confirm TestPyPI install works before tagging `v0.2.0`.

# Part 3. What is left, per the final plan

Each item: files, how to do it, how to test it.

## 3.1 Must do before 0.2.0 release

| Item | Files | How | Test |
|---|---|---|---|
| Yank 0.1.2 | PyPI web | Manage, Releases, 0.1.2, Yank | `pip install gitgrounded` refuses 0.1.2 |
| Trusted publishers | PyPI and TestPyPI settings | workflow `publish.yml`, environments `pypi` and `testpypi` | tag `v0.2.0rc1`, check TestPyPI |
| Real model run | none | Part 2, T1 to T5 | numbers look sane, cost noted |
| Noise floor gates | `engine.py` thresholds, `gitgrounded.yml` gates | tune after T2 | baseline vs baseline is PASS 10 runs in a row |
| Prompt tuning | `coverage/extract.py`, `coverage/synthesize.py`, `coverage/validate.py`, `judges/rubrics/*.yaml` | iterate on T5 output | human checklist of rules all extracted |
| HTML visual check | `report/templates/*` | open reports in light and dark mode, phone width | nothing overflows, filters work |

## 3.2 Gaps inside built features

| Item | Files | How | Test |
|---|---|---|---|
| Config pair CLI (`--base-overlay`, `--head-overlay`) | `cli/main.py`, `engine.py` | load two YAML overlays, call `overlay_variant`, then `run_variants` | same prompt, two models, verdict differs |
| LLM confirmation for behavior merges | `coverage/extract.py` `dedupe` | for pairs between 0.85 and 0.92 similarity ask the generator `same: true/false` | unit test with mock that returns false keeps both |
| App specific dimension proposals | `coverage/dimensions.py`, `pipeline.py` | `propose_dimensions` task, show in `discover`, accept via config | discover prints proposed dimensions |
| Equivalent mutant detection | `coverage/mutate.py`, `pipeline.py` | ask the validator if the mutated text changes required behavior; exclude from score | score excludes flagged mutants |
| Repair loop needs real models | `pipeline.py` `_repair` | already wired; check with T5 | `added_cases` non empty for survivors |
| Presidio redaction option | `coverage/logs.py`, `pyproject.toml` extra | use Presidio analyzer if installed | names and addresses redacted |
| Browser Sigstore check | `verifier/index.html` | bundle `sigstore` npm package with esbuild into one inline script | T7 with a CI bundle shows identity verified |
| Unstable status tuning | `engine.py` `_case_result` | after T2 with trials 3 | unstable count stable across reruns |
| Price table refresh | `config/defaults.yaml` | check current provider prices | cost line matches provider dashboards |
| Old `.versions` history import | `store/history.py`, `cli/main.py` | `history import .versions` converting v1 JSON to new format | your old labels show in `history list` |

## 3.3 Planned and not built

| Roadmap item | Files to add | How | Test |
|---|---|---|---|
| 4.7 Reference benchmark | `bench/` folder, `bench/run.py` | 3 apps (triage JSON, RAG FAQ, tool agent) x 30 injected regressions; compare auto suite vs a 20 case hand suite; output a table and a signed bundle | reproducible table; publish in README |
| 6.5 Agent framework adapters | `examples/langgraph_agent`, `examples/openai_agents`, `examples/claude_agent_sdk` | each wraps the agent and returns `{"output", "tool_calls"}` from `run(case_input, ctx)` | trace assertions catch a changed tool order |
| 6.4 Sandbox fixtures for MCP calls | `targets/mcp_server.py` | `case.context.fixtures` returned instead of calling downstream services | runs without network |
| 7.1 Marketplace action repo | new repo `gitgrounded-action` | copy `action/action.yml` to its root, tag `v1` | consumer workflow in README works |
| 7.4 Docs site | `mkdocs.yml`, `docs/*` | MkDocs Material, config reference from `gitgrounded schema`, Pages deploy workflow | site builds in CI |
| Docker publish | `.github/workflows/docker.yml` | build multi arch, push to GHCR, sign with cosign | `docker run ghcr.io/amareshhebbar/gitgrounded --version` |
| 8.1 Coverage target | `tests/*` | raise to 85 percent on `coverage/`, `stats/`, `evidence/`; add JS and Python Merkle equivalence test via Node in CI | coverage report in CI |
| 8.2 Security review | `SECURITY.md`, `targets/http_json.py` | document SSRF risk, add allowlist option for http targets, fuzz zip reader | security checklist done |
| 8.3 Async executor | `exec/executor.py` | async per provider with jitter; target 200 cases x 2 x 3 trials under 10 minutes on Groq | timed run |
| 8.4 Freeze formats | `docs/`, `config/schema.py` | declare config v1, case v1, bundle `ggb/1` stable; remove legacy flags at 1.0 | changelog notes |
| 8.5 1.0 release | tags | SLSA provenance already in `publish.yml` | `gh attestation verify` on the wheel |
| 9 Launch | blog, demo video | follow ROADMAP Phase 9 | stars, Action installs |

## 3.4 Suggested order for the next two weeks

1. Day 1: commits 1 to 24 from Part 1, push, CI green.
2. Day 2 to 3: T1 to T6 with real keys, tune gates and prompts, fix whatever T11 reveals.
3. Day 4: T8 Sigstore in CI, then yank 0.1.2, trusted publishers, `v0.2.0rc1`, `v0.2.0`.
4. Day 5 to 7: config pair CLI, equivalent mutants, history import.
5. Week 2: reference benchmark (4.7), then soft launch `discover` plus coverage report as planned.
