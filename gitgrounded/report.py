import json


def score_case(judged):
    checks = judged["code_checks"]
    scores = judged["scores"]

    if not checks["valid_json"] or checks["missing_fields"] or checks["invalid_category"] or checks["invalid_priority"]:
        return {"status": "FAIL", "reason": "code checks failed", **judged}

    groundedness = scores.get("groundedness", 0)
    format_correctness = scores.get("format_correctness", 0)
    rule_following = scores.get("rule_following", 0)
    meaning_drift = scores.get("meaning_drift", 0)

    if groundedness < 5 or rule_following < 5:
        status = "FAIL"
    elif groundedness < 7 or meaning_drift > 6 or format_correctness < 7:
        status = "WARN"
    else:
        status = "PASS"

    return {"status": status, **judged}


def aggregate(judged_cases):
    scored = [score_case(j) for j in judged_cases]

    fail_count = sum(1 for s in scored if s["status"] == "FAIL")
    warn_count = sum(1 for s in scored if s["status"] == "WARN")
    pass_count = sum(1 for s in scored if s["status"] == "PASS")

    if fail_count > 0:
        verdict = "FAIL"
    elif warn_count > 0:
        verdict = "WARN"
    else:
        verdict = "PASS"

    def avg(key):
        vals = [s["scores"].get(key, 0) for s in scored if s.get("scores")]
        return round(sum(vals) / len(vals), 2) if vals else 0

    summary = {
        "verdict": verdict,
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "total_cases": len(scored),
        "avg_groundedness": avg("groundedness"),
        "avg_format_correctness": avg("format_correctness"),
        "avg_rule_following": avg("rule_following"),
        "avg_meaning_drift": avg("meaning_drift"),
    }

    return summary, scored


def write_report(summary, cases, generated_cases, diff_text, old_ref, new_ref, path="report.json"):
    report = {
        "old_ref": old_ref,
        "new_ref": new_ref,
        "diff": diff_text,
        "summary": summary,
        "cases": cases,
        "generated_cases": generated_cases,
    }
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return report
