# Build status

Tests: 103 passing offline, coverage 85 percent (CI gate 85) (`GITGROUNDED_OFFLINE=1 pytest -q`). Nothing has been run against real models yet.

## Built

| Area | What |
|---|---|
| Packaging | src layout, working console command, extras, release pipeline with wheel smoke tests, TestPyPI on rc tags |
| Config | typed `gitgrounded.yml` v1, `GITGROUNDED_<PROVIDER>_<FIELD>` env, role env (`GITGROUNDED_JUDGE` and others), `doctor --ping` |
| Providers | OpenAI, Claude, Groq, DeepSeek, Ollama, any OpenAI compatible host, offline mock |
| Targets | python function, framework adapters (LangGraph, LangChain, Strands, CrewAI, OpenAI Agents SDK, Pydantic AI, LlamaIndex, AutoGen, smolagents, Haystack, DSPy, generic), HTTP, prompt on any provider, MCP, A2A, ADK |
| Commands | `run`, `compare`, `benchmark`, `check`, `rank`, `discover`, `synth`, `mutate`, `suite review/coverage/import`, `report`, `bundle`, `verify`, `calibrate`, `mcp diff/serve`, `history list/delete/import`, `doctor`, `init`, `schema`, `cache clear` |
| Locked questions | behavior extraction with merge confirmation, proposed app dimensions, covering arrays, synthesis with oracles, validation, diversity, logs (regex or Presidio), sealing |
| Judging | assertions, rubric, pairwise both orders, panels, calibration, trap checks before certification |
| Statistics | trials, bootstrap CIs, paired permutation tests, Holm, Wilson, unstable cases, cost, latency |
| Mutation | 6 prompt operators plus model downgrade, equivalent mutant detection, repair, minimal suite |
| Evidence | canonical records, Merkle root, Ed25519 and Sigstore signing, GitHub attestation, certificate bundles with nested pair bundles, CLI and browser verification (nested included) |
| Reports | terminal, HTML, Markdown, JUnit, JSON, coverage page, certificate page, leaderboard page |
| Distribution | GitHub Action, GitLab template, pre commit hooks, Dockerfile, Docker publish workflow with cosign, MkDocs site workflow with the verifier at `/verify` |
| Security | HTTP host allowlist, safe YAML, no shell, zip hardening, header redaction, localhost only review server |
| Benchmark | `bench/run.py` auto suite vs hand suite on planted faults |

## Needs you

1. Apply the patch, run `pytest`.
2. `gitgrounded doctor --ping` with real keys.
3. `compare --certify` and `benchmark --certify` with real models; check trap thresholds and generated questions.
4. `python bench/run.py --mutants 30` with real models; publish the table.
5. Push, check Tests, Docs and dogfood workflows; run one Sigstore signed certificate in CI.
6. Enable GitHub Pages (Actions source).
7. Yank 0.1.2, add trusted publishers, tag `v0.2.0rc1`, then `v0.2.0`.
8. Create repo `gitgrounded-action`, copy `action/action.yml` to its root, tag `v1`, publish to the Marketplace.

## Added in v5

| Item | What |
|---|---|
| Real framework examples | `examples/real_agents`: real LangGraph StateGraph with ToolNode, real Strands Agent, both offline via scripted models, real models via `SUPPORT_MODEL` |
| Real A2A and ADK | real a2a-sdk server (A2A 1.0 `SendMessage` and 0.3 `message/send`, target auto detects), real ADK agent via ADK fast API app |
| PDF and QR | `certificate.pdf` inside the certificate bundle, QR holds id, verdict and certificate.json sha256; extra `gitgrounded[pdf]` |
| Prices | table refreshed 2026-10-04 (Claude, OpenAI, Groq, DeepSeek); DeepSeek default model is now `deepseek-flash` |
| Async and rate limits | `execution.mode: async`, `execution.requests_per_minute`, per provider `GITGROUNDED_<PROVIDER>_RPM`, `GITGROUNDED_TARGET_RPM`, `GITGROUNDED_EXEC_MODE` |
| Legacy flags | removed; old flags print the replacement command |
| Independent certifier | `gitgrounded certifier serve`, `gitgrounded certify-remote`, status `VERIFIED_INDEPENDENT` when the certifier key is pinned with `--public-key`; browser verifier accepts `?key=` |

## Not built

| Item | Note |
|---|---|
| Hosted certifier | code is done; you need to deploy it (TLS, your judge keys, token list) and publish its key id |
