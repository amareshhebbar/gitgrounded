from gitgrounded.report import score_case, aggregate

GOOD_CHECKS = {"valid_json": True, "missing_fields": [], "invalid_category": False, "invalid_priority": False}
BAD_CHECKS = {"valid_json": False, "missing_fields": ["policy_line"], "invalid_category": True, "invalid_priority": True}


def make_case(checks, scores):
    return {"input": "msg", "code_checks": checks, "scores": scores, "old_raw": "{}", "new_raw": "{}"}


def test_code_check_failure_forces_fail():
    case = make_case(BAD_CHECKS, {"groundedness": 10, "format_correctness": 10, "rule_following": 10, "meaning_drift": 0})
    result = score_case(case)
    assert result["status"] == "FAIL"


def test_low_groundedness_fails():
    case = make_case(GOOD_CHECKS, {"groundedness": 3, "format_correctness": 9, "rule_following": 9, "meaning_drift": 0})
    result = score_case(case)
    assert result["status"] == "FAIL"


def test_low_rule_following_fails():
    case = make_case(GOOD_CHECKS, {"groundedness": 9, "format_correctness": 9, "rule_following": 2, "meaning_drift": 0})
    result = score_case(case)
    assert result["status"] == "FAIL"


def test_moderate_drift_warns():
    case = make_case(GOOD_CHECKS, {"groundedness": 8, "format_correctness": 8, "rule_following": 8, "meaning_drift": 7})
    result = score_case(case)
    assert result["status"] == "WARN"


def test_high_everything_passes():
    case = make_case(GOOD_CHECKS, {"groundedness": 9, "format_correctness": 9, "rule_following": 9, "meaning_drift": 1})
    result = score_case(case)
    assert result["status"] == "PASS"


def test_aggregate_verdict_is_worst_case():
    cases = [
        make_case(GOOD_CHECKS, {"groundedness": 9, "format_correctness": 9, "rule_following": 9, "meaning_drift": 1}),
        make_case(GOOD_CHECKS, {"groundedness": 8, "format_correctness": 8, "rule_following": 8, "meaning_drift": 7}),
        make_case(BAD_CHECKS, {"groundedness": 0, "format_correctness": 0, "rule_following": 0, "meaning_drift": 10}),
    ]
    summary, scored = aggregate(cases)
    assert summary["verdict"] == "FAIL"
    assert summary["pass_count"] == 1
    assert summary["warn_count"] == 1
    assert summary["fail_count"] == 1
    assert summary["total_cases"] == 3


def test_aggregate_all_pass():
    cases = [make_case(GOOD_CHECKS, {"groundedness": 9, "format_correctness": 9, "rule_following": 9, "meaning_drift": 0}) for _ in range(5)]
    summary, scored = aggregate(cases)
    assert summary["verdict"] == "PASS"
    assert summary["fail_count"] == 0
    assert summary["warn_count"] == 0