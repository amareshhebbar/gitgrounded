from gitgrounded.llm import call_json_with_retry
from gitgrounded import cache

SYSTEM = """You are a test case generator for an AI-driven support triage system. You are given a git diff of a prompt file and/or model config. Your job is to write test inputs most likely to expose regressions caused by this exact change.

Return a JSON object with a single key "cases", an array of 15 to 20 objects, each with an "id" and an "input" field. The "input" should be a realistic customer support message. Bias the inputs toward scenarios that specifically stress the part of the prompt or config that changed."""


def generate_cases(diff_text, mode, providers_config, count_hint="15 to 20"):
    cached = cache.get("generate", diff_text, count_hint)
    if cached is not None:
        return cached["cases"]

    cfg = providers_config["test_generator"][mode]
    user = f"Diff:\n{diff_text}\n\nGenerate {count_hint} test cases as described."

    parsed, _raw = call_json_with_retry(
        provider=cfg["provider"],
        model=cfg["model"],
        system=SYSTEM,
        user=user,
        providers_config=providers_config,
    )

    cache.set("generate", parsed, diff_text, count_hint)
    return parsed["cases"]