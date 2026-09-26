import os

from gitgrounded import versions
from gitgrounded.api_client import call_endpoint
from gitgrounded.judge import ai_judge

IDENTICAL_SCORES = {
    "groundedness": 10,
    "format_correctness": 10,
    "rule_following": 10,
    "meaning_drift": 0,
    "reason": "answer text identical to the previous version, no judging needed",
}


def score_pair(scores):
    groundedness = scores.get("groundedness", 0)
    format_correctness = scores.get("format_correctness", 0)
    rule_following = scores.get("rule_following", 0)
    meaning_drift = scores.get("meaning_drift", 0)

    if groundedness < 5 or rule_following < 5:
        return "FAIL"
    if groundedness < 7 or meaning_drift > 6 or format_correctness < 7:
        return "WARN"
    return "PASS"


def judge_or_skip(old_a, new_a, mode, providers_config):
    if old_a.get("raw") == new_a.get("raw"):
        return IDENTICAL_SCORES
    return ai_judge("", new_a["input"], old_a, new_a, mode, providers_config)


def rank_history(label_or_url, mode, providers_config, base_dir):
    label = versions.safe_label(label_or_url)
    version_dir = os.path.join(base_dir, ".versions", label)
    latest = versions.latest_version(version_dir)

    if latest is None:
        return {"error": f"no stored versions for '{label_or_url}'"}
    if latest < 2:
        return {"error": f"only 1 version stored for '{label_or_url}', nothing to rank yet"}

    transitions = []
    best_version = 1

    for n in range(1, latest):
        old_data = versions.load_version(version_dir, n)
        new_data = versions.load_version(version_dir, n + 1)
        old_by_input = {a["input"]: a for a in old_data["answers"]}
        new_by_input = {a["input"]: a for a in new_data["answers"]}
        shared = [k for k in new_by_input if k in old_by_input]

        scored = []
        for k in shared:
            old_a = old_by_input[k]
            new_a = new_by_input[k]
            scores = judge_or_skip(old_a, {**new_a, "input": k}, mode, providers_config)
            scored.append(score_pair(scores))

        fail_count = scored.count("FAIL")
        warn_count = scored.count("WARN")
        verdict = "FAIL" if fail_count else ("WARN" if warn_count else "PASS")

        if verdict == "PASS":
            best_version = n + 1
        elif verdict == "WARN" and (scored.count("PASS") >= fail_count + warn_count):
            best_version = n + 1

        transitions.append({
            "from": n,
            "to": n + 1,
            "verdict": verdict,
            "pass": scored.count("PASS"),
            "warn": warn_count,
            "fail": fail_count,
            "total": len(scored),
        })

    return {"label": label, "total_versions": latest, "transitions": transitions, "best_version": best_version}


def run_compare(url, label, messages, mode, providers_config, base_dir, timeout=60):
    new_answers = []
    for msg in messages:
        result = call_endpoint(url, msg, timeout=timeout)
        new_answers.append({"input": msg, "raw": result["raw"], "parsed": result["parsed"], "valid_json": result["valid_json"]})

    version_dir = os.path.join(base_dir, ".versions", versions.safe_label(label))
    latest_n = versions.latest_version(version_dir)

    if latest_n is None:
        n = versions.save_version(version_dir, {"answers": new_answers})
        return {"stored_only": True, "version": n}

    old_data = versions.load_version(version_dir, latest_n)
    old_by_input = {a["input"]: a for a in old_data["answers"]}

    cases = []
    for new_a in new_answers:
        old_a = old_by_input.get(new_a["input"])
        if old_a is None:
            cases.append({"input": new_a["input"], "status": "NEW", "scores": None})
            continue
        scores = judge_or_skip(old_a, new_a, mode, providers_config)
        status = score_pair(scores)
        cases.append({
            "input": new_a["input"],
            "status": status,
            "scores": scores,
            "old_raw": old_a.get("raw"),
            "new_raw": new_a.get("raw"),
        })

    new_n = versions.save_version(version_dir, {"answers": new_answers})

    pass_count = sum(1 for c in cases if c["status"] == "PASS")
    warn_count = sum(1 for c in cases if c["status"] == "WARN")
    fail_count = sum(1 for c in cases if c["status"] == "FAIL")
    verdict = "FAIL" if fail_count else ("WARN" if warn_count else "PASS")

    return {
        "stored_only": False,
        "compared_against_version": latest_n,
        "new_version": new_n,
        "verdict": verdict,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "total": len(cases),
        "cases": cases,
    }