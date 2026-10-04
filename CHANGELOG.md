# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project intends to follow [Semantic Versioning](https://semver.org/).


## Unreleased (v5)

* Real LangGraph, Strands, A2A (1.0 and 0.3) and ADK examples with tests
* A2A target speaks protocol 1.0 and 0.3 (`protocol: auto`)
* certificate.pdf with QR code in certificate bundles
* independent certification service and `certify-remote` client
* async executor mode and rate limiting for targets and providers
* refreshed price table
* removed legacy hackathon flags

## [Unreleased]

### Added

* Installable package with a working `gitgrounded` console command, src layout, project root discovery and a `.gitgrounded/` state folder in the user's project.
* `gitgrounded.yml` v1 with typed validation, environment interpolation and a JSON schema (`gitgrounded schema`).
* Targets: python callables in isolated worker processes per git worktree, HTTP JSON endpoints with templated bodies and JSONPath extraction, OpenAI compatible chat with a system prompt file, MCP servers over stdio or HTTP, agent traces.
* Providers: Anthropic, OpenAI, Groq and any OpenAI compatible host, Ollama, and a deterministic offline provider (`GITGROUNDED_OFFLINE=1`).
* Deterministic assertions, configurable rubric judges, pairwise judge with order swapping, judge panels and calibration against human labels.
* Statistics: trials, bootstrap intervals, paired permutation tests with Holm correction, Wilson intervals, unstable case detection, cost and latency.
* Gates with a safe expression language and a trace of which rule decided the verdict.
* Reports: terminal, self contained HTML, Markdown for pull requests, JUnit XML, JSON.
* Coverage engine: behavior extraction, covering array planning, synthesis with oracles, validation, diversity selection, production log analysis, mutation testing with repair, suite minimization, human review UI, versioned suites.
* Evidence bundles with canonical records, Merkle root, Ed25519 or Sigstore signatures, `gitgrounded verify` and a browser verifier.
* MCP schema diff with semver suggestion and GitGrounded as an MCP server.
* GitHub Action with signing, attestation, artifacts and a sticky pull request comment.

### Changed

* The command line is now subcommand based. The old flags still work for one release and print a deprecation notice.
* The triage demo moved to `examples/triage` and is created with `make_demo_repo.py`.

### Removed

* `requirements.txt`, the Streamlit dashboard, committed reports and pitch files.

## [0.1.2] (hackathon release)


### Added

- Git mode: diff two git branches of a local app, auto-generate targeted
  regression tests from the diff, judge old vs new answers, return
  PASS / WARN / FAIL.
- `--demo {safe,citation,model}` shortcuts to three built-in fixture
  branches for fast, repeatable demos.
- `--rank` for git mode (rank cached demo scenarios) and for endpoint mode
  (rank a label's full version history in plain language).
- Endpoint mode: test any live HTTP API against its own stored version
  history, since you can't diff someone else's code.
  - `--compare URL --label NAME` — snapshot and judge a live endpoint
    against its last saved version.
  - `--check` — sweep every target in `gitgrounded.yml`, or check one
    endpoint directly with positional args.
  - `gitgrounded.yml` — a registry of named endpoints and their question
    sets.
  - `--labels` — list all stored version labels.
  - `--del-v LABEL [VERSION]` / `--del-v-all` — delete one version or wipe
    all stored version history.
- `--app-module` — point git mode at any importable app module (default
  `app.triage`), not just the bundled example.
- `--quick` — sample a smaller case set for fast iteration during live
  editing.
- Four LLM providers behind one interface (`gitgrounded/llm.py`): Ollama
  (local/free), Groq (fast cloud inference), Claude/Anthropic (used as the
  judge — a different vendor from the app under test, to avoid
  self-grading bias), and a deterministic `mock` provider for offline
  tests and CI.
- `GITGROUNDED_MODE` env var (`test` / `dev` / `demo`) to switch providers
  without touching code.
- Diff-based response caching (`.cache/`) so repeated runs over an
  unchanged diff are near-instant.
- Retry with backoff and re-ask-for-valid-JSON handling for all LLM calls.
- Example Flask server (`servers/chatbots.py`) serving three real,
  independently-editable chatbot endpoints for live endpoint-mode demos.
- Streamlit dashboard reading `report.json`.
- Offline pytest suite (22 tests) running entirely on the mock provider,
  plus a separate live-demo GitHub Actions workflow.

### Fixed

- Judge cache was silently ineffective: only judge/generate calls were
  cached, so non-deterministic re-answers from the app under test changed
  the judge's cache key on every run. Fixed by caching the app's own
  answers inside `run_case()`.
- False FAILs on endpoints that were never touched, caused by normal LLM
  sampling variance rather than real drift. Mitigated by skipping the
  judge entirely when raw answer text is byte-identical
  (`judge_or_skip`), and by setting `temperature=0.1, seed=42` on Ollama
  and Groq calls to reduce (not eliminate) sampling noise.

## [0.1.0] — initial hackathon build

- Initial prototype built for the BITSoM Vertex Builders Pitch Fest,
  Software Automation AI Track.