# GitGrounded

[![Tests](https://github.com/amareshhebbar/gitgrounded/actions/workflows/tests.yml/badge.svg)](https://github.com/amareshhebbar/gitgrounded/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/gitgrounded.svg)](https://pypi.org/project/gitgrounded/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

Regression tests and benchmarks for LLM apps that write themselves, and reports nobody can quietly edit.

GitGrounded does three things:

1. **Builds your benchmark for you.** It reads your system prompt, policy documents and MCP tool schemas, extracts every behavior your app is supposed to have, generates a diverse test suite that covers them across styles, languages, difficulty and adversarial conditions, and proves the suite is strong with mutation testing.
2. **Tells you exactly what a change did.** Compare two git refs (or your uncommitted work) of a prompt, model, tool or agent. Every case is run on both versions, checked with deterministic assertions and LLM judges, and summarized with confidence intervals and significance tests.
3. **Produces evidence you can hand to customers and investors.** Every run can be packaged as a signed, hash chained `.ggb` bundle. Change one byte and verification fails. In CI the signature is bound to your GitHub workflow identity and logged in the public Sigstore transparency log.

## Install

```bash
pip install "gitgrounded[sign]"
pip install "gitgrounded[all]"
```

Try it without API keys: every LLM call can run on a deterministic offline provider.

```bash
export GITGROUNDED_OFFLINE=1
```

## Compare prompts and models in three commands

```bash
pip install "gitgrounded[sign]"
cp .env.example .env
gitgrounded compare --prompt v1.txt --prompt v2.txt --model openai --model claude --certify --open
```

Supported providers: OpenAI, Claude, Groq, DeepSeek, Ollama and any OpenAI compatible host. Supported targets: python functions, HTTP APIs, prompts on any provider, MCP servers, A2A agents and Google ADK agents. See [docs/compare.md](docs/compare.md).

## Benchmark any framework or agent

```bash
gitgrounded benchmark --spec spec.txt --context policy.md --certify --open
```

Targets can be LangGraph, LangChain, Strands, CrewAI, OpenAI Agents SDK, Pydantic AI, LlamaIndex, AutoGen, smolagents, Haystack, DSPy, any Python object with `invoke`, `run` or `chat`, plus A2A agents, Google ADK agents, MCP servers and HTTP APIs. All of them answer the same locked question set and are ranked on one leaderboard. See [docs/frameworks.md](docs/frameworks.md).

## Five minute demo

```bash
git clone https://github.com/amareshhebbar/gitgrounded
python gitgrounded/examples/triage/make_demo_repo.py /tmp/triage-demo
cd /tmp/triage-demo
export GITGROUNDED_OFFLINE=1

gitgrounded run --base baseline --head test/safe-wording-tweak
gitgrounded run --base baseline --head test/drop-citation-rule --bundle --open
gitgrounded verify .gitgrounded/runs/*/evidence.ggb

gitgrounded discover --suite auto
gitgrounded synth --suite auto
gitgrounded mutate --suite auto
gitgrounded suite coverage --suite auto --open
```

## Use it on your app

```bash
cd your-app
gitgrounded init
```

Edit `gitgrounded.yml` to point at your app. Four target types are supported:

```yaml
targets:
  app_python:
    type: python
    entry: app.bot:run
    watch: [prompts/system.txt, config/model.yaml]

  app_prompt:
    type: openai_chat
    system_prompt_file: prompts/system.txt
    model: {provider: openai, model: gpt-4.1-mini}

  app_http:
    type: http
    url: https://api.example.com/chat
    headers: {Authorization: "Bearer ${API_TOKEN}"}
    body: {message: "{{input}}"}
    output: $.reply.text

  tools:
    type: mcp
    transport: stdio
    command: ["python", "server.py"]
```

A python target is any function `run(case_input, ctx)` returning a string or a dict with `output`, and optionally `tool_calls`, `context` and `usage`. It runs in a separate process inside a git worktree of each ref, so code changes are tested, not only prompt files.

## Commands

| Command | What it does |
|---|---|
| `gitgrounded run --base main` | compare your uncommitted work against `main` |
| `gitgrounded run --base v1.2 --head feature/x` | compare two refs |
| `gitgrounded rank --base main a b c` | rank several candidates against one baseline |
| `gitgrounded check` | call live HTTP targets and compare with their stored history |
| `gitgrounded discover` | list the behaviors extracted from your prompt and documents |
| `gitgrounded synth` | generate or incrementally update the benchmark suite |
| `gitgrounded suite review` | approve, edit or reject generated cases in a local web UI |
| `gitgrounded mutate` | inject faults into the prompt and measure how many the suite detects |
| `gitgrounded suite coverage --open` | coverage report with behavior table, heatmap and mutants |
| `gitgrounded verify bundle.ggb` | verify an evidence bundle |
| `gitgrounded mcp diff --base main` | classify MCP tool schema changes as breaking, risky or safe |
| `gitgrounded mcp serve` | expose GitGrounded to coding agents as an MCP server |
| `gitgrounded calibrate --labels labels.jsonl` | measure judge agreement with human labels |
| `gitgrounded report --format html` | render the latest run |

Useful flags: `--quick`, `--trials N`, `--minimal`, `--budget-usd 2`, `--bundle`, `--fail-on warn`, `--format json|markdown`.

## How a verdict is reached

* Assertions (`json_schema`, `one_of`, `contains`, `regex`, `tool_called`, `refusal`, custom python and more) run first. A case that newly fails an assertion is a regression.
* Rubric judges score each output against the case expectations and your context documents.
* A pairwise judge compares base and head in both orders; order dependent answers count as ties.
* Every metric gets a bootstrap 95% interval, the delta gets a paired permutation p value with Holm correction, pass rates get Wilson intervals.
* Gates in `gitgrounded.yml` decide PASS, WARN or FAIL, and the report shows which rule fired.

```yaml
gates:
  fail_if: ["new_assertion_failures > 0", "fail_cases > 0"]
  warn_if: ["warn_cases > 0", "delta.score.ci_upper < 0"]
```

## Automatic benchmarks

See [docs/coverage.md](docs/coverage.md). In short: behavior extraction with source tracing, pairwise covering arrays over test conditions, synthesis with per case oracles, diversity selection, validation by a second model, mutation testing with automatic repair, a minimal CI suite, production log clustering, and human review.

## Evidence bundles

See [docs/evidence.md](docs/evidence.md). Bundles contain canonical records, a Merkle root, the resolved config, the suite, the change diff, a self contained HTML report and a signature. Verify on the command line, with `gh attestation verify`, or by dropping the file on the [browser verifier](verifier/index.html).

## GitHub Action

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
      - uses: amareshhebbar/gitgrounded/action@main
        with:
          suite: core
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

The action runs the suite, signs the bundle with your workflow identity, creates a GitHub attestation, uploads the report and bundle, and keeps one updated comment on the pull request.

## Development

```bash
pip install -e ".[dev,mcp]"
GITGROUNDED_OFFLINE=1 pytest -q
ruff check src tests examples
```

## License

MIT
