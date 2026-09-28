# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project intends to follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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