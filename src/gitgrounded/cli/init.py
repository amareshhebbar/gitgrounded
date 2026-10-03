from pathlib import Path

from rich.console import Console

console = Console()

TEMPLATE = """version: 1

project:
  name: {name}

providers:
  judge:
    provider: anthropic
    model: claude-sonnet-4-6
  generator:
    provider: anthropic
    model: claude-sonnet-4-6

targets:
  app:
    type: openai_chat
    system_prompt_file: prompts/system.txt
    watch:
      - prompts/system.txt
    model:
      provider: openai
      model: gpt-4.1-mini

suites:
  core:
    target: app
    cases: gitgrounded.cases.jsonl
    judges:
      - type: rubric
        rubric: grounded_answer
      - type: pairwise
    generate:
      count: 6
      domain: describe your app in one sentence here

  auto:
    target: app
    generate:
      enabled: false
    coverage:
      sources:
        system_prompt: prompts/system.txt
        documents: []
      budget_cases: 80
      min_cases_per_behavior: 3

gates:
  fail_if:
    - "new_assertion_failures > 0"
    - "fail_cases > 0"
  warn_if:
    - "warn_cases > 0"
    - "delta.score.mean < -0.5"

evidence:
  sign: auto
"""

CASES = """{"id": "example-1", "input": "Replace this with a real user message", "expectations": [{"kind": "must", "text": "describe what a correct answer must do"}]}
{"id": "example-2", "input": "Another realistic user message", "expectations": [{"kind": "must_not", "text": "describe what a correct answer must never do"}]}
"""

PROMPT = "You are a helpful assistant for ACME. Answer only questions about ACME products. Always be concise.\n"

GITIGNORE_LINES = [
    ".gitgrounded/cache/",
    ".gitgrounded/runs/",
    ".gitgrounded/worktrees/",
    ".gitgrounded/mutants/",
    ".gitgrounded/history/",
]


def init_project(root: Path, force: bool = False) -> int:
    cfg = root / "gitgrounded.yml"
    if cfg.exists() and not force:
        console.print(f"{cfg} already exists (use --force to overwrite)")
        return 1
    cfg.write_text(TEMPLATE.format(name=root.name or "my-app"), encoding="utf-8")
    cases = root / "gitgrounded.cases.jsonl"
    if not cases.exists():
        cases.write_text(CASES, encoding="utf-8")
    prompt = root / "prompts" / "system.txt"
    if not prompt.exists():
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text(PROMPT, encoding="utf-8")
    gi = root / ".gitignore"
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    missing = [line for line in GITIGNORE_LINES if line not in existing]
    if missing:
        with gi.open("a", encoding="utf-8") as f:
            if existing and existing[-1].strip():
                f.write("\n")
            f.write("\n".join(missing) + "\n")
    console.print("created gitgrounded.yml, gitgrounded.cases.jsonl and prompts/system.txt")
    console.print("next steps:")
    console.print("  1. point targets.app at your app (python callable, http endpoint or prompt file)")
    console.print("  2. gitgrounded synth --suite auto        generate a benchmark from your prompt")
    console.print("  3. gitgrounded run --base HEAD           compare your uncommitted change against HEAD")
    console.print("  try without API keys: export GITGROUNDED_OFFLINE=1")
    return 0
