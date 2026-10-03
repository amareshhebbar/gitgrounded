import hashlib
import json
import os
import re
from pathlib import Path

import yaml

ALLOWED_PRIORITIES = ["low", "medium", "high"]
CATEGORY_RULES = [
    ("refund", ["refund", "money back", "changed my mind"]),
    ("billing", ["charged", "charge", "invoice", "billing"]),
    ("technical", ["crash", "error", "bug", "dashboard", "not working"]),
    ("account", ["locked", "login", "password", "account", "export"]),
    ("shipping", ["package", "delivery", "shipping", "arrive"]),
]


def _offline() -> bool:
    return (
        os.environ.get("GITGROUNDED_OFFLINE", "").lower() in ("1", "true", "yes")
        or os.environ.get("GITGROUNDED_MODE", "") == "test"
    )


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _best_policy_line(policy: str, message: str) -> str:
    words = {w[:5] for w in re.findall(r"[a-z]{4,}", message.lower())}
    best, best_score = "none", 0
    for line in policy.splitlines():
        line = line.strip()
        if not re.match(r"^\d+\.", line):
            continue
        score = len(words & {w[:5] for w in re.findall(r"[a-z]{4,}", line.lower())})
        if score > best_score:
            best, best_score = line, score
    return best


def _mock(system: str, policy: str, message: str, model: str) -> str:
    low = message.lower()
    category = "other"
    for cat, keys in CATEGORY_RULES:
        if any(k in low for k in keys):
            category = cat
            break
    priority = "high" if category in ("technical", "billing") or "enterprise" in low else "medium"
    line = _best_policy_line(policy, message)
    cites = re.search(r"cite the exact policy line", system, re.I) is not None
    small_model = re.search(r"(?<![0-9])(20b|8b)\b|mini|small", model) is not None
    if small_model and int(hashlib.sha256(message.encode()).hexdigest(), 16) % 2 == 0:
        priority = "urgent"
    answer = f"Per our policy: {line}" if line != "none" and cites else "Please contact support for details."
    return json.dumps(
        {
            "category": category,
            "priority": priority,
            "answer": answer,
            "policy_line": line if cites else "",
        }
    )


def _live(system: str, message: str, cfg: dict) -> tuple[str, dict]:
    from openai import OpenAI

    provider = cfg.get("provider", "groq")
    base_url = cfg.get("base_url") or ("https://api.groq.com/openai/v1" if provider == "groq" else None)
    key_env = cfg.get("api_key_env") or ("GROQ_API_KEY" if provider == "groq" else "OPENAI_API_KEY")
    client = OpenAI(api_key=os.environ[key_env], base_url=base_url)
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": message}],
        response_format={"type": "json_object"},
        temperature=float(cfg.get("temperature", 0)),
    )
    usage = (
        {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens} if resp.usage else {}
    )
    return resp.choices[0].message.content or "", usage


def run(case_input, ctx):
    root = Path(ctx.get("root", "."))
    message = case_input if isinstance(case_input, str) else case_input[-1]["content"]
    policy = _read(root, "data/policy.md")
    system = _read(root, "prompts/triage.txt").replace("{{policy}}", policy)
    model_cfg = yaml.safe_load(_read(root, "config/model.yaml"))
    if _offline():
        raw, usage = _mock(system, policy, message, model_cfg.get("model", "")), {}
    else:
        raw, usage = _live(system, message, model_cfg)
    try:
        output = json.loads(raw)
    except json.JSONDecodeError:
        output = raw
    return {"output": output, "usage": usage, "model": model_cfg.get("model"), "context": [policy]}
