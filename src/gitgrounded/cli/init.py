import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests
from rich.console import Console

console = Console()

TEMPLATE = """version: 1

project:
  name: {name}

providers:
  judge:
    provider: {provider}
    model: {model}
  generator:
    provider: {provider}
    model: {model}

targets:
  app:
    type: openai_chat
    system_prompt_file: prompts/system.txt
    watch:
      - prompts/system.txt
    model:
      provider: {provider}
      model: {model}

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


PROVIDERS = {
    "anthropic": (
        "claude-sonnet-4-6",
        ("GITGROUNDED_ANTHROPIC_API_KEY", "GITGROUNDED_CLAUDE_API_KEY", "ANTHROPIC_API_KEY"),
    ),
    "openai": ("gpt-4.1-mini", ("GITGROUNDED_OPENAI_API_KEY", "OPENAI_API_KEY")),
    "groq": ("openai/gpt-oss-120b", ("GITGROUNDED_GROQ_API_KEY", "GROQ_API_KEY")),
    "deepseek": ("deepseek-flash", ("GITGROUNDED_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY")),
    "ollama": ("qwen2.5:7b", ()),
}


def _ollama_running() -> bool:
    try:
        return requests.get("http://localhost:11434/api/tags", timeout=0.5).status_code == 200
    except requests.RequestException:
        return False


def detect_provider(environ: dict[str, str] | None = None, probe_ollama: bool = True) -> tuple[str, str] | None:
    env = os.environ if environ is None else environ
    for name in ("anthropic", "openai", "groq", "deepseek"):
        model, keys = PROVIDERS[name]
        if any(env.get(k) for k in keys):
            return name, model
    if probe_ollama and _ollama_running():
        return "ollama", PROVIDERS["ollama"][0]
    return None


def _inside_git(root: Path) -> bool:
    r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def ensure_git(root: Path, assume_yes: bool) -> bool:
    if shutil.which("git") is None:
        console.print("git is not installed; GitGrounded compares git refs, install git first")
        return False
    if _inside_git(root):
        return True
    if not assume_yes:
        if not sys.stdin.isatty():
            console.print("this folder is not a git repository. run:")
            console.print("  git init && git add -A && git commit -m 'gitgrounded init'")
            return False
        answer = input("this folder is not a git repository. initialize one now? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            console.print(
                "skipped; run `git init && git add -A && git commit -m 'gitgrounded init'` before `gitgrounded run`"
            )
            return False
    steps = [["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "gitgrounded init"]]
    for cmd in steps:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            console.print(f"`{' '.join(cmd)}` failed: {(r.stderr or r.stdout).strip()[-300:]}")
            console.print("fix the git setup (for example `git config user.email you@example.com`) and commit once")
            return False
    console.print("initialized a git repository and made a first commit")
    return True


def init_project(
    root: Path, force: bool = False, provider: str | None = None, assume_yes: bool = False, git: bool = True
) -> int:
    cfg = root / "gitgrounded.yml"
    if cfg.exists() and not force:
        console.print(f"{cfg} already exists (use --force to overwrite)")
        return 1
    if provider and provider not in PROVIDERS:
        console.print(f"unknown provider {provider!r}; choose one of {', '.join(PROVIDERS)}")
        return 2
    if provider:
        chosen: tuple[str, str] | None = (provider, PROVIDERS[provider][0])
    else:
        from gitgrounded.providers.base import is_offline

        chosen = detect_provider(probe_ollama=not is_offline())
    if chosen is None:
        chosen = ("anthropic", PROVIDERS["anthropic"][0])
        have_key = False
    else:
        have_key = True
    cfg.write_text(
        TEMPLATE.format(name=root.name or "my-app", provider=chosen[0], model=chosen[1]),
        encoding="utf-8",
    )
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
    if have_key:
        console.print(f"using provider {chosen[0]} ({chosen[1]}) for the app, judge and generator")
    else:
        console.print("no provider key or running Ollama found; the config defaults to anthropic.")
        console.print(
            "set a key (ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY or DEEPSEEK_API_KEY) and rerun with --force,"
        )
        console.print("or try everything offline with GITGROUNDED_OFFLINE=1")
    if git:
        ensure_git(root, assume_yes)
    console.print("next steps:")
    console.print("  1. point targets.app at your app (python callable, http endpoint or prompt file)")
    console.print("  2. gitgrounded synth --suite auto        generate a benchmark from your prompt")
    console.print("  3. gitgrounded run --base HEAD           compare your uncommitted change against HEAD")
    console.print("  try without API keys: export GITGROUNDED_OFFLINE=1")
    return 0
