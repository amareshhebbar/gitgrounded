from gitgrounded.judge import code_checks


def test_valid_result_passes_all_checks():
    result = {
        "valid_json": True,
        "parsed": {"category": "billing", "priority": "medium", "answer": "x", "policy_line": "y"},
    }
    checks = code_checks(result)
    assert checks["valid_json"] is True
    assert checks["missing_fields"] == []
    assert checks["invalid_category"] is False
    assert checks["invalid_priority"] is False


def test_invalid_json_fails_everything():
    result = {"valid_json": False, "parsed": None}
    checks = code_checks(result)
    assert checks["valid_json"] is False
    assert checks["invalid_category"] is True
    assert checks["invalid_priority"] is True


def test_missing_required_field_detected():
    result = {
        "valid_json": True,
        "parsed": {"category": "billing", "priority": "medium", "answer": "x"},
    }
    checks = code_checks(result)
    assert "policy_line" in checks["missing_fields"]


def test_invalid_category_detected():
    result = {
        "valid_json": True,
        "parsed": {"category": "not-a-category", "priority": "medium", "answer": "x", "policy_line": "y"},
    }
    checks = code_checks(result)
    assert checks["invalid_category"] is True


def test_invalid_priority_detected():
    result = {
        "valid_json": True,
        "parsed": {"category": "billing", "priority": "urgent", "answer": "x", "policy_line": "y"},
    }
    checks = code_checks(result)
    assert checks["invalid_priority"] is True