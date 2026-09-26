import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from gitgrounded.llm import call
from gitgrounded.config import load_yaml, get_mode

ALLOWED_CATEGORIES = ["billing", "technical", "account", "shipping", "refund", "other"]
ALLOWED_PRIORITIES = ["low", "medium", "high"]


def load_policy():
    with open(os.path.join(BASE_DIR, "data", "policy.md")) as f:
        return f.read()


def load_prompt(prompt_path=None):
    path = prompt_path or os.path.join(BASE_DIR, "prompts", "triage.txt")
    with open(path) as f:
        return f.read()


def load_model_config(model_config_path=None):
    path = model_config_path or os.path.join(BASE_DIR, "config", "model.yaml")
    cfg = load_yaml(path)
    return cfg[get_mode()]


def load_providers_config():
    return load_yaml(os.path.join(BASE_DIR, "config", "providers.yaml"))


def run(message, prompt_text=None, model_config=None, providers_config=None):
    policy = load_policy()
    prompt_template = prompt_text if prompt_text is not None else load_prompt()
    model_cfg = model_config if model_config is not None else load_model_config()
    providers_cfg = providers_config if providers_config is not None else load_providers_config()

    system = prompt_template.replace("{{policy}}", policy)

    raw = call(
        provider=model_cfg["provider"],
        model=model_cfg["model"],
        system=system,
        user=message,
        json_mode=True,
        providers_config=providers_cfg,
    )

    try:
        parsed = json.loads(raw)
        return {"raw": raw, "parsed": parsed, "valid_json": True}
    except json.JSONDecodeError:
        return {"raw": raw, "parsed": None, "valid_json": False}


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "I was charged twice, can I get a refund?"
    result = run(msg)
    print(json.dumps(result, indent=2))
