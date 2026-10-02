import pytest

from gitgrounded.errors import ConfigError
from gitgrounded.gates import decide, evaluate_gate

NS = {
    "fail_cases": 0,
    "warn_cases": 2,
    "delta": {"score": {"mean": -0.7, "ci_upper": -0.1}},
    "pairwise": {"head_win_rate": 0.2, "base_win_rate": 0.5},
}


def test_simple_comparisons():
    assert evaluate_gate("warn_cases > 0", NS)
    assert not evaluate_gate("fail_cases > 0", NS)
    assert evaluate_gate("delta.score.ci_upper < 0", NS)
    assert evaluate_gate("pairwise.base_win_rate > pairwise.head_win_rate", NS)


def test_missing_values_never_trigger():
    assert not evaluate_gate("delta.groundedness.mean < -1", NS)


def test_boolean_ops():
    assert evaluate_gate("warn_cases > 0 and delta.score.mean < -0.5", NS)
    assert evaluate_gate("fail_cases > 0 or warn_cases > 1", NS)


def test_rejects_calls():
    with pytest.raises(ConfigError):
        evaluate_gate("__import__('os').system('true')", NS)


def test_decide_trace():
    verdict, trace = decide(["fail_cases > 0"], ["warn_cases > 0"], NS)
    assert verdict == "WARN"
    assert [t["triggered"] for t in trace] == [False, True]
