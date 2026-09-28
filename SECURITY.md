# Security Policy

GitGrounded is a small, mostly solo-maintained project. This policy is
best-effort, not an enterprise SLA — please read it with that in mind.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a security problem.

Instead, use GitHub's private vulnerability reporting form:

**https://github.com/amareshhebbar/gitgrounded/security/advisories/new**

This opens a private conversation visible only to you and the maintainer.

### What to include

- A description of the issue and its potential impact
- Steps to reproduce (a minimal example is ideal)
- The version/commit you tested against

### What to expect

- Acknowledgment within **7 days**
- A plan (fix, mitigation, or explanation of why it's out of scope) within
  **30 days**

This is a best-effort target from a small project, not a contractual
guarantee.

## In scope

- Leakage of API keys or secrets (Groq, Anthropic, Ollama config)
- Unsafe handling of `--app-module` (arbitrary Python import) leading to
  unintended code execution beyond what a user explicitly pointed it at
- Unsafe parsing/handling of `gitgrounded.yml`
- Vulnerabilities in the example Flask server (`servers/chatbots.py`)

## Things to know (project-specific risks)

- **Endpoint mode stores full responses.** `--compare` / `--check` save
  complete request/response text under `.versions/<label>/`. Don't point
  GitGrounded at an endpoint that returns real customer data, and don't
  commit `.versions/` to git (it's already gitignored).
- **The example server is a dev server, not production software.**
  `servers/chatbots.py` runs Flask's built-in development server. It has no
  auth, no rate limiting, and is meant to run on `localhost` only. Never
  expose it to the public internet.
- **`--app-module` executes arbitrary Python.** Git mode imports whatever
  module you pass (default `app.triage`) and calls it directly. Only point
  this at code you trust — it is equivalent to running that code yourself.

## Out of scope

- Issues that require prior compromise of your machine or your `.env` file
- Missing auth/rate-limiting on the example demo server (documented above,
  by design — it's a demo, not a deployable service)
- AI output quality issues (wrong verdicts, false PASS/FAIL) — these are
  real bugs worth reporting, but as a normal GitHub issue, not a security
  advisory