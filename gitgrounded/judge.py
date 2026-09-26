import json

from gitgrounded.llm import call_json_with_retry
from gitgrounded import cache

ALLOWED_CATEGORIES = ["billing", "technical", "account", "shipping", "refund", "other"]
ALLOWED_PRIORITIES = ["low", "medium", "high"]
REQUIRED_FIELDS = ["category", "priority", "answer", "policy_line"]

JUDGE_SYSTEM = """You are a strict evaluator for an AI support triage system. You are given the company policy, a customer message, an old answer, and a new answer. Score the new answer on four dimensions, each 0 to 10:

- groundedness: is the new answer fully supported by the policy, with no invented facts?
- format_correctness: does it look like a well-formed, sensible triage response?
- rule_following: does it follow the instruction to cite an exact policy line, and stay within allowed categories/priorities?
- meaning_drift: how much the meaning of the answer changed from old to new (0 = identical meaning, 10 = completely different meaning or contradictory)

Return a JSON object with keys: groundedness, format_correctness, rule_following, meaning_drift, reason (a one-sentence explanation)."""


def code_checks(result):
    if not result.get("valid_json"):
        return {
            "valid_json": False,
            "missing_fields": REQUIRED_FIELDS,
            "invalid_category": True,
            "invalid_priority": True,
        }

    parsed = result["parsed"]
    missing = [f for f in REQUIRED_FIELDS if f not in parsed]
    invalid_category = parsed.get("category") not in ALLOWED_CATEGORIES
    invalid_priority = parsed.get("priority") not in ALLOWED_PRIORITIES

    return {
        "valid_json": True,
        "missing_fields": missing,
        "invalid_category": invalid_category,
        "invalid_priority": invalid_priority,
    }


def ai_judge(policy, message, old_result, new_result, mode, providers_config):
    cache_key = json.dumps(
        {"m": message, "o": old_result.get("raw"), "n": new_result.get("raw")},
        sort_keys=True,
    )
    cached = cache.get("judge", cache_key)
    if cached is not None:
        return cached

    cfg = providers_config["judge"][mode]
    user = json.dumps(
        {
            "policy": policy,
            "message": message,
            "old_answer": old_result.get("parsed") or old_result.get("raw"),
            "new_answer": new_result.get("parsed") or new_result.get("raw"),
        }
    )

    parsed, _raw = call_json_with_retry(
        provider=cfg["provider"],
        model=cfg["model"],
        system=JUDGE_SYSTEM,
        user=user,
        providers_config=providers_config,
    )

    cache.set("judge", parsed, cache_key)
    return parsed


def judge_case(policy, message, old_result, new_result, mode, providers_config):
    checks = code_checks(new_result)
    scores = ai_judge(policy, message, old_result, new_result, mode, providers_config)
    return {
        "input": message,
        "code_checks": checks,
        "scores": scores,
        "old_raw": old_result.get("raw"),
        "new_raw": new_result.get("raw"),
    }