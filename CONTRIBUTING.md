# Contributing to GitGrounded

Thanks for looking at this project. This is a hackathon-born tool, so the bar
here is "keep it working and keep it simple," not corporate process.

## Setup

```bash
git clone https://github.com/amareshhebbar/gitgrounded.git
cd gitgrounded
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

You do not need any API keys to develop or run tests. Everything below runs
on the free `mock` provider.

## Running tests (free, no API keys)

```bash
pytest -v
```

or a real end-to-end run using the built-in demo branches:

```bash
GITGROUNDED_MODE=test python gitgrounded.py --demo citation --quick
```

Both of these use `GITGROUNDED_MODE=test`, which routes every LLM call to a
deterministic mock. This is what CI runs, and it costs nothing.

Only use `GITGROUNDED_MODE=dev` (Ollama) or `GITGROUNDED_MODE=demo`
(Groq + Claude) if you are specifically testing real-provider behavior, and
only with your own API keys.

## Branch naming

- `feat/<short-name>` — a new feature
- `fix/<short-name>` — a bug fix
- `docs/<short-name>` — documentation only
- `test/<short-name>` — test-only changes

Note: branches like `test/safe-wording-tweak`, `test/drop-citation-rule`,
`test/model-downgrade` already exist in this repo as **demo fixtures** for
GitGrounded's own git-diff mode. Don't rename, rebase, or "clean up" those —
GitGrounded's `--demo` flag and README examples depend on their exact diffs.

## Commit messages

Format: `<type>: <what changed>`

Types: `feat`, `fix`, `test`, `config`, `docs`, `chore`

Example: `fix: cache triage app answers, not just judge calls`

Keep the first line short and factual. No need for a body unless the change
needs explaining.

## Code style

- No comments or docstrings unless a piece of logic is genuinely non-obvious
  and would be confusing without one.
- One responsibility per function.
- All provider-specific code (Ollama, Groq, Claude, mock) stays inside
  `gitgrounded/llm.py`. Nothing else should know which HTTP API it's calling.
- Anything that calls a real model must have a working mock path, so tests
  never require network access or API keys.

## Adding a new LLM provider

1. Add a `_call_<provider>()` function in `gitgrounded/llm.py` following the
   same signature as `_call_groq` / `_call_ollama`.
2. Wire it into `call()`'s dispatch.
3. Add the provider's config shape to `config/providers.yaml`.
4. Add a mock-mode equivalent so tests don't need the new provider's key.
5. Document the required env var in `.env.example` and the README.

## Never commit

- `.env` (your real API keys)
- `.cache/` (local LLM response cache)
- `.versions/` (endpoint-mode version history — may contain real response
  text)
- `report*.json` (generated run output)
- `.agents/`, `.claude/` (local AI-tooling config, not part of the project)

All of these are already in `.gitignore`. If you see one show up in
`git status`, don't force-add it.

## Pull request checklist

- [ ] `pytest -v` passes locally
- [ ] No real API keys, `.cache/`, `.versions/`, or `report*.json` in the diff
- [ ] Commit messages follow the `<type>: <what>` format
- [ ] README updated if you changed or added a CLI flag

## Reporting a security issue

Do not open a public issue for a security vulnerability — see
[SECURITY.md](SECURITY.md).

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). Be decent.