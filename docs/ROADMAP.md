# GitGrounded Execution Plan

Owner: Amaresh Hebbar
Repo: github.com/amareshhebbar/gitgrounded
Package: pypi.org/project/gitgrounded
Baseline audited: commit `fc538cd`, PyPI release `0.1.2` (uploaded 2026 09 28)
Plan start: Monday 2026 10 05
Target 1.0: week 20 (week of 2026 02 15)

# 0. How to read and run this plan

Every task in this document has four parts:

* **What:** the concrete outcome.
* **How:** the implementation steps, files, interfaces and commands.
* **Why:** the reason the task exists and why this approach beats the obvious alternative.
* **Done when:** a check you can run to prove the task is finished.

Execution rules for the whole build:

1. One branch per task: `p<phase>/<task-id>-<slug>`, for example `p0/0.2-src-layout`.
2. One PR per task, merged to `main` only when its "Done when" check passes in CI.
3. Every phase ends with a tagged release. Never start a phase while the previous one is unreleased.
4. The triage example must stay green after every merge. It is the canary that proves the core is still general.
5. Docs for a feature land in the same PR as the feature.
6. Track tasks in a GitHub Project board with columns Backlog, This week, In progress, Review, Done. Task ids in this document become issue titles.

# 1. Audit of the current state

## 1.1 What works today

* Git mode compares two refs of one hardcoded app (`prompts/triage.txt` plus `config/model.yaml`), generates targeted cases from the diff, judges old vs new, prints PASS / WARN / FAIL.
* Endpoint mode (`--compare`, `--check`) POSTs `{"message": ...}` to a URL, stores answers under `.versions/<label>/vN.json`, judges the newest run against the previous one.
* `--rank` ranks refs (git mode) or walks stored history (endpoint mode).
* Providers: ollama, groq, claude, mock. Response cache. 22 offline tests. PR comment workflow. Tag based trusted publishing workflow.

## 1.2 Defects found, ranked by severity

1. **PyPI 0.1.2 is broken.** Entry point `gitgrounded.cli:main` points at a module that does not exist. The wheel ships without `config/`, `app/`, `prompts/`, `data/`.
2. **Root `gitgrounded.py` collides with the `gitgrounded/` package.** Import resolution depends on the working directory.
3. **All paths resolve from `BASE_DIR`** (the install location). Installed from PyPI, state would be written into `site-packages`.
4. **Triage logic is hardcoded in the core.** `judge.py` hardcodes categories, priorities, fields. `generate.py` hardcodes "customer support message". `runner.py` hardcodes two watched files.
5. **Endpoint mode judges with an empty policy**, so groundedness there is scored against nothing.
6. **Endpoint contract is fixed** to `POST {"message": ...}`. No headers, auth, templates, response extraction, OpenAI chat format.
7. **Git mode ranking sorts only by `avg_groundedness`.** A version with a FAIL can rank first.
8. **Single sample, single judge, no statistics.** Scores cannot be defended.
9. **Results are not shown.** Terminal prints counts only.
10. **Reports are editable JSON** with no provenance.
11. **No coverage story.** Test inputs come from a 5 item seed file plus 15 to 20 generated cases. Nobody can say which rules of the system prompt were tested and which were not.
12. Hygiene: committed reports and pitch binaries, issue templates in the wrong folder, malformed `.gitignore`, pinned `requirements.txt` vs unpinned `pyproject.toml`, PR workflow posts a new comment on every push, hardcoded model ids.

# 2. Project definition

## 2.1 One line

GitGrounded automatically builds a benchmark for your AI app from its system prompt, tools and docs, tells you exactly what a prompt, model, tool or agent change did to it, and produces a signed report anyone can verify was not edited.

## 2.2 The three pillars (the reasons someone picks this over promptfoo, DeepEval, Braintrust, LangSmith)

1. **Automatic benchmark synthesis with measured coverage.** Developers do not write test questions. GitGrounded reads the system prompt, policies, tool schemas and optional production logs, extracts every behavior the app is supposed to have, generates a diverse case set that covers them, and proves the set is good by mutation testing. Answers the problem: "my prompt covers so much that I cannot even list what to test."
2. **Change targeted regression testing.** Reads the diff, focuses tests on what changed, reports the delta with statistics.
3. **Verifiable evidence.** Every run is a signed, hash chained bundle tied to a commit and CI identity, logged in a public transparency log, verifiable in one command or one web page.

## 2.3 Users

* App developer: CI gate for prompt and model changes, with zero test writing.
* MCP server author: knows whether a schema or description change breaks tool selection.
* Founder or vendor: hands a verifiable quality report to customers, auditors, investors.
* Buyer, auditor, VC: verifies the report without trusting the sender.

## 2.4 In scope for 1.0

* Targets: Python callable, HTTP JSON endpoint, OpenAI compatible chat endpoint, MCP server, agent trace.
* Coverage engine: behavior extraction, dimension model, combinatorial planning, synthesis with oracles, diversity control, validation, mutation scoring, log seeding, human review, versioned suites.
* Change sources: git refs, live endpoint history, config pairs.
* Checks: deterministic assertions, rubric judge, pairwise judge, judge panel.
* Statistics: trials, bootstrap intervals, paired significance, judge calibration.
* Outputs: terminal, JSON, HTML, Markdown, JUnit.
* Evidence: canonical bundle, Merkle root, Sigstore signing, GitHub attestation, `verify` command, browser verifier.
* Distribution: PyPI, GitHub Action, Docker image, docs site.

## 2.5 Out of scope for 1.0

* Hosted SaaS, production tracing, red teaming suites, prompt optimization, fine tuning.
* Claiming "tamper proof." The claim is **tamper evident and independently verifiable**. Why: nothing stops a person editing a file; what we guarantee is that the edit is detectable and the original producer is provable. Using the accurate claim protects credibility in front of technical buyers.

## 2.6 Success metrics

* Zero to first verified report in under 10 minutes with zero hand written test cases.
* Mutation score of auto generated suites at or above 0.85 on the reference apps.
* 500 stars and 20 external repos using the Action within 90 days of 1.0.
* 3 public signed reports from real projects linked in the README.

# 3. Target architecture

## 3.1 Package layout

```
gitgrounded/
  pyproject.toml
  src/gitgrounded/
    __init__.py
    __main__.py
    project.py
    cli/
      main.py
      cmd_init.py
      cmd_run.py
      cmd_check.py
      cmd_rank.py
      cmd_discover.py
      cmd_synth.py
      cmd_suite.py
      cmd_mutate.py
      cmd_report.py
      cmd_verify.py
      cmd_history.py
      cmd_mcp.py
    config/
      schema.py
      loader.py
      defaults.yaml
    targets/
      base.py
      python_callable.py
      http_json.py
      openai_chat.py
      mcp_server.py
      agent.py
    sources/
      git_source.py
      history_source.py
      config_pair_source.py
    coverage/
      ingest.py
      extract.py
      behavior_map.py
      dimensions.py
      planner.py
      synthesize.py
      oracle.py
      diversity.py
      validate.py
      mutate.py
      minimize.py
      logs.py
      suite_store.py
      review_server.py
    cases/
      model.py
      loader.py
    assertions/
      registry.py
      builtin.py
    judges/
      base.py
      rubric.py
      pairwise.py
      panel.py
      rubrics/
    providers/
      base.py
      openai_compat.py
      anthropic.py
      ollama.py
      mock.py
      embeddings.py
    exec/
      executor.py
      budget.py
    stats/
      intervals.py
      significance.py
      ranking.py
      reliability.py
    store/
      cache.py
      history.py
    evidence/
      canonical.py
      merkle.py
      bundle.py
      sign_sigstore.py
      sign_local.py
      verify.py
    report/
      model.py
      terminal.py
      html.py
      markdown.py
      junit.py
      templates/
    mcp/
      introspect.py
      schema_diff.py
      selection_eval.py
      call_eval.py
      server.py
  examples/
  action/action.yml
  verifier/index.html
  tests/
  docs/
```

## 3.2 Data flow

```
sources of truth                     coverage engine                         regression run                     evidence
system prompt, policy,     ->  extract behaviors -> dimensions ->   base variant + head variant          ->  canonical records
tool schemas, logs             plan cells -> synthesize + oracle    x suite cases x trials                  -> merkle root
                               -> diversify -> validate              -> target.invoke -> transcripts        -> signature + attestation
                               -> mutate + minimize                  -> assertions + judges                 -> report.html
                               -> versioned suite (hashed)           -> stats -> gate verdict               -> verify
```

## 3.3 Config v1 (`gitgrounded.yml`)

```yaml
version: 1

project:
  name: acme-support-bot
  state_dir: .gitgrounded

providers:
  judge:
    provider: anthropic
    model: claude-sonnet-4-5
    temperature: 0
  generator:
    provider: anthropic
    model: claude-sonnet-4-5
  embeddings:
    provider: local
    model: sentence-transformers/all-MiniLM-L6-v2

targets:
  support_bot:
    type: python
    entry: app.triage:run
    watch:
      - prompts/triage.txt
      - config/model.yaml
  live_api:
    type: http
    url: https://api.acme.com/chat
    headers:
      Authorization: "Bearer ${ACME_TOKEN}"
    body: { "message": "{{input}}" }
    output: "$.reply.text"

coverage:
  sources:
    system_prompt: prompts/triage.txt
    documents:
      - data/policy.md
    tools: []
    logs: logs/prod_sample.jsonl
  dimensions:
    style: [terse, verbose, typo_heavy, angry, code_mixed_hinglish]
    language: [en, hi]
    difficulty: [easy, edge, adversarial]
  strength: 2
  budget_cases: 150
  min_cases_per_behavior: 3
  mutation_target: 0.85

suites:
  core:
    target: support_bot
    cases: .gitgrounded/suites/core/current.jsonl
    assertions:
      - type: json_valid
      - type: json_schema
        schema: schemas/triage.schema.json
    judges:
      - type: rubric
        rubric: grounded_answer
      - type: pairwise
    trials: 3

gates:
  fail_if:
    - "assertion_failures > 0"
    - "delta.groundedness.ci_upper < -0.5"
  warn_if:
    - "delta.meaning_drift.mean > 2"

evidence:
  sign: auto
  attest: github
  redact:
    - "$.request.headers.Authorization"
```

## 3.4 CLI v1

```
gitgrounded init
gitgrounded discover
gitgrounded synth --suite core
gitgrounded suite review core
gitgrounded suite coverage core
gitgrounded mutate --suite core
gitgrounded run --base main --head HEAD
gitgrounded check
gitgrounded rank --base main feature/a feature/b
gitgrounded history live_api --rank
gitgrounded report out/run.ggb --format html --open
gitgrounded verify out/run.ggb
gitgrounded mcp diff --base main --head HEAD --target weather_mcp
gitgrounded mcp serve
```

# 4. Phases

Week numbering starts at week 1 = 2026 10 05.

## Phase 0: Stabilize and repackage (week 1)

Goal: `pip install gitgrounded` gives a working command in any folder.

### 0.1 Yank 0.1.2

* **What:** 0.1.2 is marked yanked on PyPI.
* **How:** pypi.org, Your projects, gitgrounded, Manage, Releases, 0.1.2, Options, Yank, reason "broken console entry point, use 0.2.0 or later".
* **Why:** a yanked release is skipped by `pip install gitgrounded` unless pinned exactly, so new users stop hitting the crash. Deleting would permanently burn the version number and gives no extra benefit.
* **Done when:** `pip install gitgrounded` in a fresh venv says no matching distribution (until 0.2.0 ships), and the PyPI page shows the yanked label.

### 0.2 Move to src layout, kill the root script

* **What:** package lives at `src/gitgrounded/`, CLI at `src/gitgrounded/cli/main.py`, no top level `gitgrounded.py`.
* **How:**
```
git checkout -b p0/0.2-src-layout
mkdir -p src
git mv gitgrounded src/gitgrounded
mkdir -p src/gitgrounded/cli
git mv gitgrounded.py src/gitgrounded/cli/main.py
touch src/gitgrounded/cli/__init__.py
printf 'from gitgrounded.cli.main import main\n\nmain()\n' > src/gitgrounded/__main__.py
```
In `main.py` delete the `BASE_DIR` and `sys.path` block. In `pyproject.toml`:
```toml
[project.scripts]
gitgrounded = "gitgrounded.cli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/gitgrounded"]

[tool.hatch.build.targets.sdist]
include = ["src", "tests", "README.md", "LICENSE", "CHANGELOG.md"]

[tool.pytest.ini_options]
pythonpath = ["src", "."]
```
* **Why:** src layout forces tests to run against the installed package, not the working tree, which is exactly the class of bug that shipped in 0.1.2. Removing the root script removes the name collision.
* **Done when:** `pip install -e . && gitgrounded --help && python -m gitgrounded --help` both work from `/tmp`.

### 0.3 Project root resolver and state directory

* **What:** all reads and writes resolve against the user's project, never the install directory.
* **How:** `src/gitgrounded/project.py`:
```python
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Project:
    root: Path
    config_path: Path | None
    state_dir: Path

    @property
    def cache_dir(self) -> Path:
        return self.state_dir / "cache"

    @property
    def history_dir(self) -> Path:
        return self.state_dir / "history"

    @property
    def runs_dir(self) -> Path:
        return self.state_dir / "runs"

    @property
    def suites_dir(self) -> Path:
        return self.state_dir / "suites"

    def resolve(self, path: str | os.PathLike) -> Path:
        p = Path(path)
        return p if p.is_absolute() else (self.root / p).resolve()


def _git_toplevel(start: Path) -> Path | None:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def find_project(start: Path | None = None, config_name: str = "gitgrounded.yml") -> Project:
    start = (start or Path.cwd()).resolve()
    for d in [start, *start.parents]:
        candidate = d / config_name
        if candidate.is_file():
            return Project(d, candidate, d / ".gitgrounded")
    root = _git_toplevel(start) or start
    return Project(root, None, root / ".gitgrounded")
```
Replace every `BASE_DIR` usage with `project.resolve(...)` or the typed dirs. `cache.py` takes `cache_dir` as an argument instead of a module constant.
* **Why:** a CLI tool must behave like `git`: find its config by walking up. Writing into `site-packages` breaks on read only installs, pipx, Docker, and leaks data between projects.
* **Done when:** `grep -rn BASE_DIR src/` is empty, and running in a temp project creates only `<tmp>/.gitgrounded/`.

### 0.4 Move the triage demo out of the core

* **What:** `examples/triage/` contains `app/`, `prompts/`, `data/`, `config/`, `servers/`, and its own `gitgrounded.yml`.
* **How:** `git mv app prompts data config servers examples/triage/`. Ship provider defaults as `src/gitgrounded/config/defaults.yaml` loaded via `importlib.resources.files("gitgrounded.config") / "defaults.yaml"`. Keep the old behavior working temporarily by having the triage example's yml point at its own files.
* **Why:** the wheel should contain the tool, not one demo app. It also forces Phase 1 to make the core general.
* **Done when:** `python -m zipfile -l dist/*.whl` lists only `gitgrounded/...` and dist info.

### 0.5 Dependencies

* **What:** one source of truth in `pyproject.toml`.
* **How:**
```toml
dependencies = [
  "PyYAML>=6.0",
  "requests>=2.31",
  "openai>=1.40",
  "anthropic>=0.40",
  "python-dotenv>=1.0",
  "jinja2>=3.1",
  "rich>=13.7",
  "pydantic>=2.7",
  "numpy>=1.26",
]

[project.optional-dependencies]
coverage = ["sentence-transformers>=3.0", "datasketch>=1.6", "allpairspy>=2.5"]
mcp = ["mcp>=1.0"]
sign = ["sigstore>=3.0", "rfc8785>=0.1", "cryptography>=42"]
dashboard = ["streamlit>=1.35"]
server = ["Flask>=3.0"]
dev = ["pytest>=8", "hypothesis>=6.100", "pytest-cov>=5", "ruff>=0.6", "build", "twine"]
```
Delete `requirements.txt`. CI installs `.[dev]`.
* **Why:** libraries must declare lower bounds, not exact pins, or they conflict with users' environments. Heavy optional features (embeddings, signing, MCP) stay as extras so the base install stays small.
* **Done when:** `pip install gitgrounded` pulls no torch; `pip install "gitgrounded[coverage]"` does.

### 0.6 Hygiene

* **What:** clean repo.
* **How:**
```
git rm report_test_*.json GitGrounded_Hackathon_One_Pager.pdf GitGrounded_Hackathon_One_Pager.pptx
git mv .github/workflows/ISSUE_TEMPLATE .github/ISSUE_TEMPLATE
```
Rewrite `.gitignore`:
```
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
.gitgrounded/cache/
.gitgrounded/runs/
.versions/
.cache/
dist/
build/
.agents/
.claude/
```
Attach the pitch files to a GitHub Release named `hackathon-2026` instead. Model ids move to `defaults.yaml`.
* **Why:** binaries bloat clones forever, misplaced templates are silently ignored by GitHub, and committed reports confuse users about what is real output.
* **Done when:** GitHub "New issue" shows the bug and feature templates.

### 0.7 Release pipeline that tests the wheel before publishing

* **What:** `publish.yml` with `build`, `smoke`, `publish_testpypi`, `publish_pypi` jobs.
* **How:**
```yaml
name: Publish
on:
  push:
    tags: ["v*"]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install build twine
      - run: python -m build
      - run: twine check dist/*
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
  smoke:
    needs: build
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ["3.11", "3.12", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - shell: bash
        run: |
          pip install dist/*.whl pytest hypothesis
          mkdir -p "$RUNNER_TEMP/empty" && cd "$RUNNER_TEMP/empty" && gitgrounded --help
      - shell: bash
        run: python -m pytest tests -q -p no:cacheprovider --import-mode=importlib
  publish_testpypi:
    needs: smoke
    if: contains(github.ref_name, 'rc')
    runs-on: ubuntu-latest
    environment: testpypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/
  publish_pypi:
    needs: smoke
    if: ${{ !contains(github.ref_name, 'rc') }}
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
```
In PyPI and TestPyPI settings, set the trusted publisher to repo `amareshhebbar/gitgrounded`, workflow `publish.yml`, environments `pypi` and `testpypi`. Delete the old `workflow.yml`.
* **Why:** 0.1.2 broke because nothing installed the wheel before upload. A smoke job on three OSes catches packaging, path and entry point bugs before they become public. Release candidates going to TestPyPI first means the real index only ever gets builds that worked.
* **Done when:** tagging `v0.2.0rc1` publishes to TestPyPI and `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ gitgrounded==0.2.0rc1` works.

### 0.8 Ship 0.2.0

* **How:** update README quick start to `pip install gitgrounded`, CHANGELOG entry, `git tag v0.2.0 && git push --tags`.
* **Why:** the public name should point at something that works before you do anything else.
* **Done when:** fresh venv, empty folder, `pip install gitgrounded && gitgrounded --help` works.

### Phase 0 day plan

* Mon: 0.1, 0.2
* Tue: 0.3
* Wed: 0.4, 0.5
* Thu: 0.6, 0.7, tag rc1
* Fri: fix rc findings, 0.8

## Phase 1: Generalize the core (weeks 2 to 4)

Goal: no triage assumptions anywhere. Any app, any prompt file, any endpoint.

### 1.1 Config schema and loader

* **What:** `gitgrounded.yml` v1 parsed into typed objects with precise errors.
* **How:** Pydantic v2 models in `config/schema.py` (`ProjectCfg`, `ProviderCfg`, `TargetCfg` as a discriminated union on `type`, `SuiteCfg`, `CoverageCfg`, `GateCfg`, `EvidenceCfg`, root `Config` with `version: Literal[1]`). `loader.py`: read YAML with `yaml.safe_load`, expand `${VAR}` with a regex over string leaves using `os.environ` and fail with the variable name when missing, merge `defaults.yaml` underneath, validate, then dump `Config.model_json_schema()` to `docs/schema.json` in CI. `gitgrounded init` writes a commented starter yml, `cases.jsonl` with two examples, and appends `.gitgrounded/cache/` to `.gitignore`.
* **Why:** config is the public API of a CLI tool. Typed validation with field paths turns "KeyError: endpoint" into "targets.live_api.url: field required", which is the difference between a user staying and leaving. Discriminated unions let each target type have its own fields without a pile of optionals.
* **Done when:** a test suite of 20 invalid yml fixtures each produces the expected error path.

### 1.2 Target adapter interface

* **What:** every system under test is reached through one interface.
* **How:** `targets/base.py`:
```python
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: Any = None


@dataclass
class Transcript:
    case_id: str
    variant: str
    trial: int
    request: dict[str, Any]
    raw_output: str
    output: Any
    tool_calls: list[ToolCall] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    provider_response_id: str | None = None
    error: str | None = None


class Target(Protocol):
    name: str

    def describe(self) -> dict[str, Any]: ...

    def invoke(self, case: "Case", variant: "Variant", trial: int) -> Transcript: ...
```
Implement `python_callable.py` (imports `module:function` inside the variant worktree, calls it with `case.input` and `variant.files`), `http_json.py` (renders `body` with `{{input}}` and `{{messages}}`, extracts `output` with `jsonpath-ng` or a small built in JSONPath subset), `openai_chat.py` (system prompt from a watched file, model from config, uses provider abstraction).
* **Why:** separating "how to call the app" from "how to evaluate it" is what lets the same evaluator serve Python apps, deployed APIs, MCP servers and agents. Capturing tokens, latency, tool calls and context in the transcript now means statistics, cost and evidence phases get their data for free.
* **Done when:** one shared contract test runs against all three adapters with a local Flask mock and a mock provider.

### 1.3 Variant sources

* **What:** a variant is a fully materialized version of the app.
* **How:** `git_source.py`: for each ref, `git worktree add --detach <state>/worktrees/<sha> <sha>`; the python target imports from that worktree with `importlib` and a temporary `sys.path` entry inside a subprocess (`multiprocessing` spawn context) so two versions of the same module never share an interpreter. Diff is `git diff <base>..<head> -- <watch paths>`. Worktrees are reused by SHA and pruned by `gitgrounded cache clear`. `history_source.py` moves endpoint history to `<state>/history/<target>/vN.json`. `config_pair_source.py` applies two YAML overlays to the same code.
* **Why:** today only the prompt string and model yaml change between versions; real changes touch code, tool definitions and retrieval settings. A worktree tests the real code at each ref. Subprocess isolation is required because Python caches imported modules, so importing two versions in one process silently tests the same code twice.
* **Done when:** an example where head changes a Python helper (not the prompt) shows different outputs between variants.

### 1.4 Case model

* **What:** JSONL cases with enough structure for coverage and oracles.
* **How:** `cases/model.py`:
```python
from typing import Any, Literal
from pydantic import BaseModel, Field


class Expectation(BaseModel):
    kind: Literal["must", "must_not", "should", "refuse", "tool_call", "format"]
    text: str
    behavior_id: str | None = None


class Case(BaseModel):
    id: str
    input: str | list[dict[str, str]]
    tags: list[str] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)
    cell: dict[str, str] = Field(default_factory=dict)
    expectations: list[Expectation] = Field(default_factory=list)
    reference: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    origin: Literal["human", "synth", "log", "diff"] = "human"
```
Dataset hash: SHA 256 over RFC 8785 canonical JSON of each case, sorted by id.
* **Why:** `behaviors`, `cell` and `expectations` are what make coverage measurable (Phase 3) and give the judge a per case oracle instead of a generic "is this good". `origin` lets reports separate human cases from synthesized ones, which matters to skeptical readers.
* **Done when:** the old `seed_cases.json` converts with `gitgrounded suite import`.

### 1.5 Assertions

* **What:** free, deterministic checks that run before any judge.
* **How:** registry keyed by `type`, each a function `(transcript, params) -> AssertionResult(passed, message)`. Built ins: `json_valid`, `json_schema` (`jsonschema` lib), `jsonpath_equals`, `one_of`, `contains`, `not_contains`, `regex`, `max_length`, `latency_ms_below`, `cost_below`, `tool_called`, `tool_not_called`, `python` (user callable `module:function`). Third party assertions via entry point group `gitgrounded.assertions`.
* **Why:** a deterministic failure is indisputable and costs nothing; an LLM judge score is an opinion. Running assertions first means the strongest evidence in a report is the cheapest to produce, and the judge only spends tokens on what code cannot check.
* **Done when:** triage's hardcoded category and priority checks are expressed purely as config assertions.

### 1.6 Providers

* **What:** one provider interface, four implementations.
* **How:** `providers/base.py` with `complete(system, messages, json_mode, temperature, seed, max_tokens) -> Completion(text, model_returned, response_id, input_tokens, output_tokens, latency_ms)`. `openai_compat.py` covers OpenAI, Groq, Together, Fireworks, OpenRouter, vLLM, LM Studio via `base_url` and `api_key_env`. `anthropic.py`, `ollama.py`, `mock.py` (deterministic, keyed by a hash of inputs, so tests can simulate a regression). Retries with exponential backoff and jitter, honoring `Retry-After`.
* **Why:** most hosts speak the OpenAI wire format, so one adapter gives broad coverage with little code. Recording the model id the provider actually returned matters because aliases silently move; the report must show what really ran.
* **Done when:** contract test passes for all four against recorded fixtures.

### 1.7 Judges

* **What:** configurable rubric judge and pairwise judge.
* **How:**
  * Rubric YAML (`judges/rubrics/grounded_answer.yaml`): dimensions with name, 0 to 10 anchors at 0, 5, 10, which context fields to show (`policy`, `reference`, `retrieved`, `expectations`). Judge prompt is built from the rubric plus the case expectations. Output schema enforced via JSON mode and validated with Pydantic; one repair retry.
  * Pairwise judge: present outputs as A and B, then again swapped. Record preference and whether both orders agree. Disagreement counts as a tie.
  * Endpoint mode gets context from `coverage.sources.documents` so groundedness is judged against real policy.
* **Why:** absolute scores drift between runs and judges; pairwise preference with order swapping is a far more stable signal for "did this change make it better or worse", which is exactly our question. Per case expectations turn a vague quality score into "did it do the specific thing this case was built to test".
* **Done when:** on a mock regression fixture, pairwise prefers base on every changed case in both orders.

### 1.8 Executor and cache

* **What:** concurrent, cached execution.
* **How:** `exec/executor.py` uses `concurrent.futures.ThreadPoolExecutor` with a per provider semaphore (`max_concurrency` in config, default 8). Cache key = SHA 256 of canonical JSON of (variant content hash, case hash, trial, provider, model, temperature, seed, rubric hash). Variant content hash = hash of watched file contents, not the ref name, so a rebased branch reuses results.
* **Why:** keying by content instead of ref name means identical variants never pay twice. Concurrency turns a 20 minute run into 3.
* **Done when:** second identical run makes zero provider calls (asserted via mock call counter).

### 1.9 Ranking fix

* **What:** ranking respects failures.
* **How:** sort key `(gate_rank, assertion_failures, -pairwise_win_rate, -primary_metric_mean)` where gate_rank is FAIL 2, WARN 1, PASS 0. After Phase 4, ties within overlapping confidence intervals are labeled "tied".
* **Why:** a version that breaks one critical case should never be called the best.
* **Done when:** fixture where the highest average has a FAIL ranks below a clean PASS.

### 1.10 Port triage to config only

* **How:** `examples/triage/gitgrounded.yml` using assertions and rubric; delete `ALLOWED_CATEGORIES` etc. from core.
* **Why:** if the flagship demo needs special code, nobody else's app will work.
* **Done when:** `grep -rn "billing\|triage" src/` is empty. Tag `v0.3.0`.

## Phase 2: Show the results (week 5)

Goal: developers see exactly what changed per case.

### 2.1 Result model

* **What:** `report/model.py` with `RunResult` (meta, variants, cases, metrics, gate trace, coverage summary slot, evidence slot).
* **How:** Pydantic models; every renderer consumes only `RunResult`.
* **Why:** one model, many renderers, and later the evidence bundle signs exactly this model. Renderers can never disagree with the signed data.
* **Done when:** JSON schema of `RunResult` generated into docs.

### 2.2 Terminal

* **How:** `rich` panels: verdict, metric table (base, head, delta, interval later), top 5 regressions and top 5 improvements with side by side truncated outputs, gate rule that fired.
* **Why:** most runs are read in a terminal or CI log; the verdict must explain itself without opening a file.

### 2.3 HTML report

* **How:** Jinja2 template, single file, inline CSS and vanilla JS, no CDN. Sections: verdict header, provenance, metric cards, coverage heatmap (filled in Phase 3), filterable case table, per case drawer with word level diff (Python `difflib.SequenceMatcher` on tokens, rendered as `<ins>`/`<del>`), judge reasoning, assertion results, raw transcripts, source diff.
* **Why:** a single offline file can be emailed, attached to a data room, and later signed. External assets would break the signature story and fail behind corporate proxies.

### 2.4 Markdown and JUnit

* **How:** Markdown summary for PR comments and `$GITHUB_STEP_SUMMARY`, worst cases in `<details>`. JUnit XML with one `testcase` per case and variant.
* **Why:** JUnit makes GitLab, Jenkins and Azure DevOps show results natively without any plugin from us.

### 2.5 Done when

`gitgrounded run` prints a readable summary and `gitgrounded report run.json --format html --open` renders offline. Tag `v0.4.0`.

## Phase 3: Coverage engine, automatic benchmark synthesis (weeks 6 to 9)

This is the answer to: "the system prompt covers a huge spread of topics and rules, developers do not want to spend time writing tests, and even when they try they cannot identify the variety of questions needed."

### 3.0 The core idea

Treat the system prompt like a specification and apply three proven software testing techniques to it:

1. **Requirement extraction:** turn the prompt and its documents into a list of atomic, testable behaviors, each traced back to the exact sentence it came from.
2. **Combinatorial test design:** pick test conditions across several dimensions (topic, input style, language, difficulty, adversarial type) using covering arrays, so every pair of conditions appears at least once without exploding into a full cartesian product. Research on real software faults (Kuhn and colleagues at NIST) found most failures are triggered by one or two interacting factors, which is why pairwise coverage gives most of the value at a tiny fraction of the cost.
3. **Mutation testing:** deliberately break the system prompt in known ways and measure which breakages the suite detects. A suite that cannot detect a deleted rule is not a benchmark, no matter how many questions it has. Mutation score is the number we publish to prove suite quality.

This combines the CheckList idea from NLP behavioral testing (Ribeiro et al., ACL 2020: test capabilities systematically in a capability by test type matrix) with classical combinatorial and mutation testing, automated end to end with LLMs.

Output: a versioned, hashed suite plus a coverage report that says "143 cases, 41 of 41 behaviors covered at least 3 times, all dimension pairs covered, mutation score 0.91."

### 3.1 Ingest sources of truth

* **What:** a normalized `SourceDoc` list from system prompt, policy and knowledge docs, MCP tool schemas, OpenAPI specs, and optional logs.
* **How:** `coverage/ingest.py` reads files listed in `coverage.sources`. Markdown and text are split into sections by headings, then into sentences with stable ids `<file>#<section>:<n>` and character offsets. Tool schemas become one `SourceDoc` per tool (name, description, params). Large knowledge bases are chunked to about 800 tokens with overlap and sampled for extraction (all prompt sentences, a stratified sample of document chunks by section).
* **Why:** stable sentence ids let every generated case point back to the exact requirement it tests. That traceability is what turns "we have 150 tests" into "rule 7 of your prompt is tested by cases 12, 48, 91" in the report.
* **Done when:** running on the triage example produces a deterministic list with ids and offsets.

### 3.2 Extract the behavior map

* **What:** `behavior_map.json`, a list of atomic behaviors.
* **How:** `coverage/extract.py`. For each prompt section, call the generator model with a structured output schema:
```python
from typing import Literal
from pydantic import BaseModel


class Behavior(BaseModel):
    id: str
    kind: Literal["capability", "rule_must", "rule_must_not", "format", "persona", "refusal", "tool_use", "escalation", "knowledge"]
    statement: str
    source_ids: list[str]
    triggers: list[str]
    observable: str
    severity: Literal["critical", "major", "minor"]
```
`observable` must describe how a correct answer is recognized ("cites one exact policy line", "returns JSON with field category"). Then a second pass merges duplicates (embedding similarity above 0.9 plus an LLM confirmation) and a third pass asks the model for **implicit** behaviors that the prompt implies but does not state (out of scope requests, ambiguous requests, conflicting user instructions, prompt injection attempts, missing information). Knowledge documents produce `knowledge` behaviors grouped by topic cluster instead of one per fact.
Every behavior's `source_ids` must resolve to real sentence ids; behaviors citing nothing are dropped unless they came from the implicit pass, where they are tagged `implicit`.
* **Why:** a prompt like "You are a support agent for billing, shipping and accounts; always cite policy; never promise refunds above 100 USD; reply in the user's language" hides at least 8 testable behaviors and several implied ones. Developers miss the implied ones most, and those are where production failures come from. Forcing an `observable` field makes every behavior judgeable; forcing `source_ids` prevents the model inventing requirements.
* **Done when:** on the triage prompt the map contains every rule a human reviewer lists in a 10 minute read (you do this once as the acceptance test and save the human list as a fixture).

### 3.3 Dimension model

* **What:** the axes along which inputs vary.
* **How:** `coverage/dimensions.py`. Built in dimensions with sensible default values:
  * `topic`: derived automatically by clustering `capability` and `knowledge` behaviors.
  * `style`: terse, verbose, polite, angry, typo_heavy, all_caps, code_mixed.
  * `language`: from config; default only the prompt's language.
  * `difficulty`: easy, edge, adversarial.
  * `adversary`: none, prompt_injection, out_of_scope, ambiguous, conflicting_instruction, missing_info, multi_intent.
  * `turns`: single, multi.
  Users override or extend in `coverage.dimensions`. An LLM pass proposes app specific dimensions (for a fitness app: user goal, experience level) which the user accepts in review.
* **Why:** behaviors say what to test; dimensions say under which conditions. A refund rule that works for a polite English message and breaks for an angry Hinglish one is the typical real failure, and nobody writes that case by hand.
* **Done when:** `gitgrounded discover` prints the behavior map and the dimension table.

### 3.4 Plan cells with covering arrays

* **What:** `plan.json`, a list of cells, each a behavior plus a value per dimension.
* **How:** `coverage/planner.py`:
  1. Per behavior, choose relevant dimensions (a `format` behavior does not need `adversary`; a `refusal` behavior forces `adversary != none`).
  2. Build a strength `t` covering array (default `t=2`, pairwise) over those dimensions with `allpairspy`; for strength 3 use a greedy IPOG implementation in `planner.py`.
  3. Allocate the budget: `cases_for_behavior = max(min_cases_per_behavior, weight * budget)` where weight is `critical 3, major 2, minor 1`, normalized. Critical behaviors get every covering array row; minor behaviors get a sample.
  4. Always include one easy, clean baseline cell per behavior so failures can be attributed to conditions, not to the behavior itself.
* **Why:** full cartesian coverage over 6 dimensions with 5 values each is 15,625 cells per behavior; pairwise needs roughly 25 to 40. Budget weighting puts spend where failures hurt. The clean baseline cell is what lets the report say "fails only under typo heavy input", which is actionable.
* **Done when:** `planner` unit test proves every value pair of every relevant dimension appears in at least one cell for each behavior.

### 3.5 Synthesize cases with oracles

* **What:** a concrete input plus expectations for every cell.
* **How:** `coverage/synthesize.py`, batched by behavior (one call creates all cells for one behavior so the model sees siblings and avoids repeats). Prompt contains: behavior statement and source sentences, the cell values, 3 example inputs from existing cases or logs for realism, a list of already generated inputs for that behavior. Output schema returns `input`, `expectations` (kind and text, each linked to `behavior_id`), and an optional `reference` answer when the behavior is factual. `oracle.py` turns expectations into concrete assertions where possible (`refuse` becomes a `refusal` rubric check, `format` becomes `json_schema` if a schema is configured, `tool_call` becomes `tool_called`) and leaves the rest for the judge. Multi turn cells produce a list of user turns.
Use a different model family for synthesis than for judging when available.
* **Why:** a test without an expected outcome only measures change, not correctness. Attaching expectations at generation time, when the model knows exactly which rule it is targeting, gives each case a precise oracle and lets the judge answer a narrow yes or no question, which is far more reliable than open ended grading. Separate model families reduce the chance that the same blind spot both writes and grades the test.
* **Done when:** every synthesized case has at least one expectation linked to a behavior id.

### 3.6 Diversity and deduplication

* **What:** no near duplicate cases; the suite spreads across the input space.
* **How:** `coverage/diversity.py`:
  1. Exact and near text duplicates removed with MinHash LSH (`datasketch`, 5 gram shingles, Jaccard threshold 0.8).
  2. Embed all inputs (`providers/embeddings.py`, local `all-MiniLM-L6-v2` by default, provider embeddings optional).
  3. Within each behavior, select the final set with maximal marginal relevance: start from the clean baseline case, then repeatedly add the candidate maximizing `lambda * relevance - (1 - lambda) * max_similarity_to_selected`, relevance being the validator score from 3.7. Generate about 1.5x the budget so selection has room.
  4. Report a diversity score per behavior: mean pairwise cosine distance.
* **Why:** LLM generators collapse into the same phrasing; 30 cases that are paraphrases of one question test one thing. Selection after over generation is cheaper and more reliable than asking the model to "be diverse".
* **Done when:** a fixture of 50 paraphrases of one question reduces to at most 5.

### 3.7 Validate cases

* **What:** every case is realistic, on target, and its expectations agree with the prompt.
* **How:** `coverage/validate.py`, a validator call per case with a different model where available, returning `realistic` (0 to 1), `targets_behavior` (bool), `expectation_consistent_with_spec` (bool, with the source sentences shown), `answerable` (bool). Drop cases failing any boolean; use `realistic` as the relevance term in 3.6. Optional self consistency: run the validator twice on a 10 percent sample and report agreement.
* **Why:** synthesis models sometimes write expectations the prompt does not support (for example inventing a refund limit). A wrong oracle produces false FAILs, and one false FAIL in front of a customer destroys trust in the tool. Validation is the cheapest place to catch it.
* **Done when:** a fixture with planted inconsistent expectations has them removed.

### 3.8 Mutation testing and suite minimization

* **What:** a mutation score for the suite and a minimal suite that keeps it.
* **How:** `coverage/mutate.py` creates mutants of the system prompt (and tool descriptions when present):
  * `delete_rule`: remove one sentence that is a source of a `rule_must`, `rule_must_not`, `refusal` or `format` behavior.
  * `negate_rule`: invert it ("always cite" to "do not cite").
  * `weaken_rule`: replace "always" or "never" with "usually".
  * `swap_value`: change numbers, limits, enum values.
  * `drop_section`: remove a whole section.
  * `model_downgrade`: swap the model for a configured smaller one.
  * `tool_description_blur`: shorten a tool description (Phase 6).
  For each mutant, run the suite (cached, single trial, assertions plus pairwise judge vs the original). A mutant is **killed** if any case linked to the mutated behavior regresses significantly, or any assertion fails. Mutation score = killed mutants / total mutants (excluding equivalent mutants flagged by the validator as no behavioral change).
  For surviving mutants, call the synthesizer again targeted at that behavior with the mutant diff as a hint ("generate inputs where this rule matters"), validate, and retry once. This loop is how the suite improves itself.
  `minimize.py`: greedy set cover keeping the smallest case set that kills the same mutants plus at least `min_cases_per_behavior` per behavior. The full suite remains available as `extended`.
* **Why:** coverage counts only prove that tests exist; mutation score proves they can detect breakage. It is also the most convincing number for a VC or customer because it is a measured detection rate on known faults, not a model's opinion. Minimization keeps CI fast and cheap: the minimal suite runs on every PR, the extended suite nightly.
* **Done when:** on the triage example, deleting the citation rule is killed by at least 3 cases, and the reported mutation score is at or above `coverage.mutation_target`.

### 3.9 Seed from production logs (optional)

* **What:** real user traffic shapes the suite and exposes gaps in the prompt itself.
* **How:** `coverage/logs.py` imports JSONL (`{"input": ..., "output": ..., "ts": ...}`) and adapters for Langfuse and LangSmith exports. Redact PII with regex detectors (email, phone, card numbers, Aadhaar and PAN patterns) plus an optional Presidio extra. Embed, cluster with HDBSCAN or k means (k chosen by silhouette), label clusters with the generator model, map clusters to behaviors by similarity. Sample representatives per cluster into the suite with `origin: log`. Report two gaps: **untested traffic** (clusters with no matching behavior, meaning users ask things the prompt never addresses) and **unseen behaviors** (behaviors with no traffic, meaning possibly dead rules).
* **Why:** synthesized inputs follow the prompt's view of the world; logs show the users' view. The gap between them is often the most valuable finding for the developer, and real phrasing makes synthesized cases more realistic when used as few shot examples.
* **Done when:** a fixture log with an off topic cluster appears as untested traffic in the coverage report.

### 3.10 Human review loop

* **What:** a fast way for a developer to accept, edit or reject synthesized cases.
* **How:** `gitgrounded suite review core` starts a local Flask server (`review_server.py`) on localhost with a single page: cases grouped by behavior, keyboard shortcuts (a accept, r reject, e edit), shows source sentences and expectations. Decisions are written to `review.jsonl`. Reviewed cases get `reviewed: true`. The report shows the percentage of reviewed cases.
* **Why:** full automation gets you a strong first suite in minutes; ten minutes of human review on critical behaviors makes it something you can defend to an auditor. Showing the reviewed percentage is honest and lets readers weigh the evidence.
* **Done when:** reviewing 50 cases takes under 5 minutes in a timed run.

### 3.11 Versioned suites and incremental regeneration

* **What:** suites are files in the repo with history and hashes.
* **How:** `suite_store.py` writes `.gitgrounded/suites/<name>/v<N>/{behavior_map.json,plan.json,cases.jsonl,coverage.json,mutation.json}` and a `current.jsonl` symlink or copy. Commit these (they are small). On prompt change, diff the behavior map between versions: unchanged behaviors keep their cases; changed or new behaviors get regenerated; removed behaviors have cases archived. In a `gitgrounded run --base X --head Y`, the run uses the suite plus extra diff targeted cases for behaviors whose source sentences changed in the diff.
* **Why:** a benchmark that regenerates from scratch every run is not a benchmark; scores would not be comparable across time. Pinning versions and hashes makes runs comparable and lets the evidence bundle prove which suite version was used. Incremental regeneration keeps cost proportional to the size of the change.
* **Done when:** editing one sentence of the prompt regenerates only the cases linked to it.

### 3.12 Coverage report

* **What:** `gitgrounded suite coverage core` and a coverage section in every HTML report.
* **How:** heatmap of behaviors (rows) vs dimension values (columns) colored by case count and pass rate; table of behaviors with severity, source sentence, case count, pass rate, mutants killed; list of surviving mutants; log gap lists; summary line with behavior coverage, pairwise coverage, mutation score, reviewed percentage.
* **Why:** this page is the answer to "how do you know your tests are good". It turns an opaque set of questions into a map anyone can audit.
* **Done when:** HTML report shows the heatmap for the triage example. Tag `v0.5.0`.

### Phase 3 week plan

* Week 6: 3.1, 3.2, 3.3
* Week 7: 3.4, 3.5, 3.6
* Week 8: 3.7, 3.8
* Week 9: 3.9, 3.10, 3.11, 3.12, release

## Phase 4: Benchmark grade statistics (weeks 10 to 11)

### 4.1 Trials

* **How:** `trials: N` per suite, default 3 locally, 5 in CI. Each trial stored separately; cache key includes trial index.
* **Why:** LLM outputs vary at any temperature above zero and often at zero too. One sample can show a regression that is pure noise.

### 4.2 Intervals

* **How:** `stats/intervals.py` with numpy: case level bootstrap (resample cases, not trials, 10,000 iterations, seed recorded) for every mean metric; Wilson score interval for pass rates.
* **Why:** resampling cases matches the question "would this hold on similar inputs". Wilson intervals behave correctly near 0 and 100 percent where the normal approximation fails.

### 4.3 Delta significance

* **How:** paired bootstrap on per case deltas for the interval; paired sign flip permutation test for the p value; Holm correction across metrics. Gates may reference `delta.<metric>.ci_lower`, `ci_upper`, `p_value`.
* **Why:** the same cases run on both variants, so paired tests are far more sensitive than comparing two independent means. Correction across metrics prevents "something is always significant" when checking many.

### 4.4 Judge reliability

* **How:** `stats/reliability.py`: pairwise position consistency rate; optional panel of 2 or 3 model families with Krippendorff alpha; judge rerun on a 10 percent sample for variance.
* **Why:** a report should state how much to trust its own judge. Publishing agreement numbers preempts the first objection every technical reader raises.

### 4.5 Calibration

* **How:** `gitgrounded calibrate --labels human.jsonl` computes Cohen kappa and Spearman between judge and human labels; result hash stored and referenced in later bundles.
* **Why:** "judge agrees with human reviewers at kappa 0.7 on 200 items" is a credible claim; "we used GPT to grade" is not.

### 4.6 Flakiness, cost, latency

* **How:** cases whose verdict flips across trials are labeled unstable and excluded from gate counts but listed. Tokens and USD per variant from a price table in defaults; p50 and p95 latency.
* **Why:** unstable cases otherwise produce random CI failures, which is the fastest way to get a tool removed from a pipeline. Cost and latency are often the real reason for a model swap and belong next to quality.

### 4.7 Reference benchmark

* **How:** `gitgrounded-bench` folder: three open example apps (triage JSON bot, RAG FAQ bot, tool using agent) with 30 known injected regressions. Measure detection rate and false positive rate of auto generated suites vs a hand written 20 case suite.
* **Why:** this is the headline evidence for launch and for investors: "auto generated suites caught 28 of 30 injected regressions; a typical hand written suite caught 11."
* **Done when:** results table generated by a script and reproducible. Tag `v0.6.0`.

## Phase 5: Signed, verifiable evidence (weeks 12 to 14)

### 5.1 Threat model

* **How:** write `docs/evidence.md` with: protected (post run edits to scores, cases, transcripts, verdicts; deleting failed cases; swapping reports between commits; backdating); not protected (cherry picked suite, mitigated by suite hash plus suite committed in the repo; judge error, mitigated by transcripts and calibration; local runs presented as CI, mitigated by identity display).
* **Why:** stating precisely what a signature proves makes the claim defensible and stops overclaiming.

### 5.2 Canonical records and Merkle root

* **How:** `evidence/canonical.py` uses the `rfc8785` package for JSON Canonicalization Scheme; floats rounded to 6 decimals before canonicalization. `merkle.py`: leaves are SHA 256 of each canonical record line, internal nodes SHA 256 of `0x01 || left || right`, leaves prefixed `0x00` (prevents second preimage tricks); odd nodes promoted. Inclusion proofs exported per case.
* **Why:** canonical JSON makes hashes identical across OSes and Python versions. A Merkle root lets one signature cover thousands of records and lets you prove a single case belongs to a report without revealing the rest, useful under NDA.

### 5.3 Bundle format `.ggb`

* **How:** zip with fixed timestamps and sorted entries (deterministic):
```
manifest.json
records/cases.jsonl
records/transcripts.jsonl
records/judgements.jsonl
records/assertions.jsonl
inputs/config.resolved.json
inputs/suite/cases.jsonl
inputs/suite/coverage.json
inputs/suite/mutation.json
inputs/change.diff
summary.json
merkle.json
signature/bundle.sigstore.json
report.html
```
`manifest.json` holds tool version and wheel hash, repo URL, base and head SHAs, config hash, suite version and hash, rubric hashes, models requested and returned, provider response ids, seeds, timestamps, runtime info, Merkle root, `summary.json` hash, `report.html` hash.
* **Why:** everything needed to audit the run travels together. Including the suite and coverage proves which questions were asked, which closes the cherry picking loophole as far as possible.

### 5.4 Sigstore keyless signing in CI

* **How:** `sign_sigstore.py` uses `sigstore` (the `sigstore-python` project) to sign the SHA 256 of `manifest.json` with the ambient GitHub Actions OIDC identity, producing a Sigstore bundle with the certificate and the Rekor transparency log inclusion proof. Requires `permissions: id-token: write`.
* **Why:** no private keys to leak or rotate. The certificate binds the signature to repo, workflow file and ref; the public Rekor log provides an independent timestamp and makes any later re signing visible.

### 5.5 GitHub artifact attestation

* **How:** in the Action, `actions/attest@v2` with `subject-path: run.ggb`, `predicate-type: https://gitgrounded.dev/attestation/eval-run/v1`, `predicate-path: manifest.json`. Requires `attestations: write`.
* **Why:** gives a second, GitHub native verification path (`gh attestation verify run.ggb --repo owner/repo`) that buyers already trust from supply chain security.

### 5.6 Local signing

* **How:** Ed25519 key generated on first use in `~/.config/gitgrounded/keys/`; bundle flagged `self_signed`; public key fingerprint printed.
* **Why:** developers need to sign outside CI, but the report must clearly show it is a weaker claim than a CI identity.

### 5.7 Redaction

* **How:** JSONPath list in `evidence.redact`; matched values replaced with `"redacted:sha256:<hash of salt||value>"`; salt stored only locally. Authorization headers always redacted.
* **Why:** reports get shared; secrets and PII must not travel with them, but redacted records must still verify.

### 5.8 `gitgrounded verify`

* **How:** unzip to memory with path traversal checks; recompute every record hash and the Merkle root; compare manifest hashes for summary and report; verify Sigstore bundle with `--identity` and `--issuer https://token.actions.githubusercontent.com` (or local public key); print VERIFIED, VERIFIED SELF SIGNED, or TAMPERED with the first mismatching file and line.
* **Why:** verification must be one command with a one word answer, or nobody will do it.

### 5.9 Browser verifier

* **How:** `verifier/index.html` on GitHub Pages. JSZip to read the bundle, Web Crypto `SHA-256` for hashing, a small JS port of the canonical and Merkle code (tested against Python golden vectors), signature verification with the `sigstore` npm package bundled via esbuild into one file. All client side, no upload. If browser signature verification proves fragile, the page verifies hashes and Merkle root fully and shows the exact `gh attestation verify` command for the signature.
* **Why:** customers and VCs will not install Python. A drag and drop page they can open from a pitch deck link, that never uploads confidential data, is what makes the evidence usable.

### 5.10 Tests

* **How:** golden bundles in `tests/fixtures`; mutation tests that flip one byte in every entry and assert TAMPERED with the right file; cross OS hash stability in the CI matrix; JS and Python produce identical roots on 1,000 random records (Hypothesis generated).
* **Done when:** a CI run on this repo produces a bundle that verifies in CLI, `gh attestation verify`, and the browser page. Tag `v0.7.0`.

## Phase 6: MCP and agent testing (weeks 15 to 17)

### 6.1 MCP adapter

* **How:** `targets/mcp_server.py` using the official `mcp` SDK, stdio and streamable HTTP transports; `initialize`, `tools/list`, `resources/list`, `prompts/list`, `tools/call`; every call recorded as a transcript.
* **Why:** MCP is where agent apps are standardizing; testing servers directly is a gap in most eval tools.

### 6.2 MCP schema diff

* **How:** `mcp/schema_diff.py` compares `tools/list` across refs. Breaking: tool removed or renamed, required param added, type narrowed, enum value removed. Risky: description changed beyond a normalized edit distance threshold, new tool overlapping an existing one by embedding similarity. Safe: optional param added, trivial wording. Output a semver suggestion and nonzero exit on breaking.
* **Why:** free, instant, no LLM, and immediately useful to every MCP author; ideal as a pre commit hook and the easiest adoption hook.

### 6.3 Coverage engine for tools

* **How:** extend 3.2 so each tool yields `tool_use` behaviors (when to call, when not to call, argument rules from the schema). Dimensions add `ambiguity_between_tools`. Mutants add `tool_description_blur` and `param_description_swap`.
* **Why:** description edits change which tool a model picks; only generated tasks that sit near decision boundaries detect that.

### 6.4 Tool selection and call evals

* **How:** selection eval gives a model the server's tool list and the task, records chosen tool and arguments, validates arguments against the input schema, compares to expectations, reports accuracy base vs head. Call eval executes fixture arguments against both versions with assertions on outputs; sandbox mode via fixture responses for downstream services.
* **Why:** measures the real behavioral effect of schema and description changes rather than guessing.

### 6.5 Agent traces and multi turn

* **How:** `targets/agent.py` wraps a callable returning messages plus tool calls; adapters in `examples/` for OpenAI Agents SDK, LangGraph and Claude Agent SDK. Trace assertions `tool_called`, `tool_not_called`, `tool_call_order`, `max_steps`, `final_answer_contains`. Multi turn cases from 3.5 run as scripted conversations.
* **Why:** agent regressions usually show up as wrong tool order or extra steps, not wrong final text.

### 6.6 GitGrounded as an MCP server

* **How:** `gitgrounded mcp serve` exposes `discover`, `synth_suite`, `run_suite`, `diff_mcp`, `verify_bundle`, `get_report`.
* **Why:** coding agents (Claude Code, Cursor) can test their own prompt edits before committing, which puts GitGrounded inside the workflows where prompts are now edited.
* **Done when:** example MCP weather server with a description edit is flagged risky and shows a measured selection accuracy change. Tag `v0.8.0`.

## Phase 7: Distribution (weeks 18 to 19)

### 7.1 GitHub Action

* **How:** separate repo `amareshhebbar/gitgrounded-action` (Marketplace requires the action at a repo root). Composite action: setup Python, `pip install gitgrounded[sign]==<pinned>`, restore cache via `actions/cache` keyed on suite hash, run, sign, attest, upload `.ggb` artifact, sticky PR comment (find existing comment by hidden marker `<!-- gitgrounded -->` and update it), write step summary, exit by gate.
Consumer workflow:
```yaml
name: GitGrounded
on: pull_request
permissions:
  contents: read
  pull-requests: write
  id-token: write
  attestations: write
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: amareshhebbar/gitgrounded-action@v1
        with:
          suite: core
          base: origin/${{ github.base_ref }}
          head: HEAD
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```
* **Why:** adoption happens when setup is one file. Sticky comments avoid spamming PRs, which is the most common complaint about bot comments.

### 7.2 Other CI and hooks

* **How:** GitLab CI template; `.pre-commit-hooks.yaml` running `gitgrounded mcp diff` and assertion only suites; Docker image on GHCR signed with cosign.
* **Why:** meets teams where they already are, with free fast checks locally and full runs in CI.

### 7.3 Cost controls

* **How:** `--budget-usd` enforced by `exec/budget.py` (estimate before run from token history, hard stop when exceeded); minimal suite on PRs, extended nightly; content hash caching.
* **Why:** an eval tool that surprises someone with a bill gets uninstalled.

### 7.4 Docs site

* **How:** MkDocs Material on GitHub Pages: Quick start, Concepts, Coverage engine, Config reference generated from schema, Targets, Assertions, Judges, Statistics, Evidence, MCP, CI recipes, FAQ, honest comparison page.
* **Done when:** a fresh repo integrates with one workflow file and `gitgrounded init`. Tag `v0.9.0`.

## Phase 8: Hardening and 1.0 (week 20)

* **8.1 Coverage:** above 85 percent on `coverage/`, `stats/`, `evidence/`; Hypothesis tests on canonicalization, Merkle, planner pair coverage.
  Why: these modules carry the credibility claims; a bug there is a false statement in someone's investor deck.
* **8.2 Security review:** safe YAML only, no `shell=True`, zip path traversal checks, SSRF warning for http targets, secrets never logged, `SECURITY.md` with disclosure contact.
* **8.3 Performance:** 200 cases x 2 variants x 3 trials under 10 minutes on Groq targets.
* **8.4 Freeze:** config v1, case schema v1, bundle v1, CLI surface; deprecation policy documented; legacy flags removed.
* **8.5 Release 1.0.0** with SLSA build provenance on the release artifacts (`actions/attest-build-provenance`).

## Phase 9: Launch (from week 21, continuous)

* **Demo:** 60 second video. Run `gitgrounded discover` on a real open source chatbot prompt, show 40 behaviors and 140 cases generated in two minutes, open a PR that deletes one rule, sticky comment shows FAIL with the killed behavior, open HTML report, drop the bundle in the verifier, VERIFIED.
  Why: the zero test writing moment plus the verify moment are the two things nobody else shows.
* **Post:** "Your AI benchmark is 20 questions you thought of. Ours is generated from your prompt and scored by mutation testing." Include the reference benchmark table.
* **Channels:** Show HN, r/LocalLLaMA, MCP community, LangChain and LlamaIndex showcases, X and LinkedIn, Product Hunt.
* **Seed users:** run `discover` plus `mcp diff` on 10 popular open source prompts and MCP servers; open issues with the findings (surviving mutants, untested rules) only where they are useful to maintainers; offer signed reports to 5 startups you know.
* **Community:** good first issues (new assertions, new target adapters, new mutation operators), monthly releases, public roadmap board.

# 5. Calendar

* Week 1 (Oct 05): Phase 0, ship 0.2.0
* Weeks 2 to 4 (Oct 12 to Oct 30): Phase 1, ship 0.3.0
* Week 5 (Nov 02): Phase 2, ship 0.4.0
* Weeks 6 to 9 (Nov 09 to Dec 04): Phase 3 coverage engine, ship 0.5.0
* Weeks 10 to 11 (Dec 07 to Dec 18): Phase 4 statistics, ship 0.6.0
* Weeks 12 to 14 (Dec 21 to Jan 08): Phase 5 evidence, ship 0.7.0
* Weeks 15 to 17 (Jan 11 to Jan 29): Phase 6 MCP and agents, ship 0.8.0
* Weeks 18 to 19 (Feb 01 to Feb 12): Phase 7 distribution, ship 0.9.0
* Week 20 (Feb 15): Phase 8, ship 1.0.0
* Week 21 onward: Phase 9 launch

Early soft launch option: after Phase 3 ships (0.5.0, early December), post `discover` plus coverage report alone. It is the most novel piece and works without signing; early feedback will sharpen Phases 4 to 6.

If teammates help: Phase 2 renderers and Phase 7 docs run in parallel with Phase 3; MCP schema diff (6.2) has no dependency beyond Phase 1 and can be built any time after week 4.

# 6. Working rhythm

## 6.1 Daily loop

1. Pick the top card in "This week".
2. Create branch `p<phase>/<id>-<slug>`.
3. Write the "Done when" check as a test first.
4. Implement until the test passes with the mock provider.
5. Run one live check on the triage example with Groq plus a cheap judge (budget capped at 0.50 USD).
6. Open PR using the checklist below, merge when CI is green.

## 6.2 PR checklist

* Done when check is an automated test.
* Triage example still passes offline.
* Docs page updated.
* CHANGELOG line under "Unreleased".
* No new hardcoded paths, models or domain words in `src/`.

## 6.3 Release checklist

```
git switch main && git pull
pytest -q
python -m build && twine check dist/*
git tag vX.Y.Zrc1 && git push origin vX.Y.Zrc1
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "gitgrounded==X.Y.Zrc1"
gitgrounded --help
git tag vX.Y.Z && git push origin vX.Y.Z
```
Then: GitHub Release notes from CHANGELOG, update docs version, post a short changelog on X and LinkedIn.

# 7. Testing strategy

* **Unit:** assertions, stats, canonicalization, Merkle, planner, diversity selection, schema diff. Pure functions, pytest plus Hypothesis.
* **Contract:** one shared suite every target adapter must pass (Flask HTTP mock, stdio MCP mock, python callable fixture).
* **Pipeline offline:** mock provider with scripted regressions; full `discover` to `synth` to `run` to `verify` on every push, Linux, macOS, Windows, Python 3.11 to 3.13.
* **Live nightly:** triage and RAG examples with Groq targets and a real judge, budget capped, bundle signed and published to GitHub Pages as a public dogfood log.
* **Benchmark nightly:** reference benchmark detection rate and mutation score; a drop fails the nightly.
* **Install test:** built wheel installed into an empty folder on every release candidate.

# 8. PyPI and naming

* Yank 0.1.2 today; do not delete.
* Trusted publishers: PyPI with `publish.yml` and environment `pypi`; TestPyPI with environment `testpypi`.
* Add to `pyproject.toml`: `authors`, `keywords` (`llm`, `evaluation`, `benchmark`, `regression-testing`, `mcp`, `prompt-engineering`, `ci`, `sigstore`, `mutation-testing`), classifiers, and `[project.urls]` Homepage, Documentation, Source, Issues, Changelog.
* Reserve now: GitHub org `gitgrounded`, repo `gitgrounded-action`, and the docs domain if you choose to buy one.

# 9. Risks and mitigations

* **Synthesized oracles are wrong:** validation pass, different model families for synth and judge, human review on critical behaviors, reviewed percentage shown in reports.
* **Behavior extraction misses rules:** human acceptance fixture on reference prompts; mutation testing exposes rules with zero killing cases; implicit behavior pass.
* **Cost of synthesis and mutation:** synthesis runs once per suite version, not per PR; mutation runs only on suite changes and nightly; cache by content hash; Groq for targets.
* **LLM judge credibility:** assertions first, pairwise with order swap, panels, calibration published.
* **Nondeterminism:** claim integrity of the recorded run, never reproducibility of outputs; trials and intervals everywhere.
* **Signature misunderstood as quality guarantee:** docs and report state exactly what the signature proves.
* **Solo bandwidth:** if time slips, cut in this order: Streamlit dashboard, Docker image, GitLab template, log seeding (3.9), multi turn (6.5). Never cut 3.2, 3.8, 5.4, 5.8; they are the differentiators.

# 10. Decisions, with recommended defaults so nothing blocks

* **Config validation:** Pydantic v2. Better errors and free JSON Schema for docs outweigh the dependency.
* **Default judge:** Claude Sonnet class model for judge, a different family (OpenAI compatible open model on Groq) for synthesis and validation, local MiniLM for embeddings. Users override in config.
* **Docs and verifier domain:** start on GitHub Pages (`amareshhebbar.github.io/gitgrounded`), buy `gitgrounded.dev` only after the launch post gains traction.
* **License:** MIT for the tool forever. Any hosted registry later is a separate product and can carry its own terms; decide that only if 1.0 shows demand.
* **Commercial home:** keep GitGrounded community first; if a hosted verification registry is built later, it is a natural fit for the Impossible AI entity rather than the core repo.
