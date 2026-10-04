## What this changes

A short description of what the PR does and why.

## Type of change

- [ ] `feat` — new feature
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `test` — test-only change
- [ ] `config` — CI, dependencies, tooling
- [ ] `chore` — anything else

## Checklist

- [ ] `pytest -v` passes locally
- [ ] No real API keys, `.cache/`, `.versions/`, or `report*.json` in the diff
- [ ] Commit messages follow `<type>: <what changed>`
- [ ] README updated if a CLI flag changed or was added
- [ ] If this touches a provider (`llm.py`), a mock-mode path still works

## How to test this

Exact commands a reviewer can run to verify the change (prefer
`GITGROUNDED_MODE=test`, no API keys needed).

```
GITGROUNDED_MODE=test python gitgrounded.py --demo citation --quick
```