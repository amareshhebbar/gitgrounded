from gitgrounded.stats.intervals import bootstrap_mean_ci, wilson
from gitgrounded.stats.ranking import rank_results
from gitgrounded.stats.reliability import cohen_kappa, krippendorff_alpha_interval, spearman
from gitgrounded.stats.significance import holm, paired_bootstrap_delta, sign_flip_p_value


def test_bootstrap_contains_mean():
    r = bootstrap_mean_ci([1, 2, 3, 4, 5], 2000, 1)
    assert r["ci_lower"] <= r["mean"] <= r["ci_upper"]


def test_wilson_edges():
    r = wilson(0, 10)
    assert r["ci_lower"] == 0 and 0 < r["ci_upper"] < 0.35
    r = wilson(10, 10)
    assert r["ci_upper"] == 1 and r["ci_lower"] > 0.65


def test_paired_delta_negative():
    d = paired_bootstrap_delta([8, 8, 8, 8, 8, 8], [5, 4, 5, 6, 4, 5], 2000, 1)
    assert d["ci_upper"] < 0


def test_sign_flip_exact_and_large():
    assert sign_flip_p_value([-3] * 10) < 0.01
    assert sign_flip_p_value([1, -1, 1, -1]) == 1.0
    assert sign_flip_p_value([-1.0] * 30) < 0.01


def test_holm_monotone():
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj["a"] <= adj["c"] <= adj["b"]


def test_agreement_metrics():
    assert cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) > 0.99
    assert krippendorff_alpha_interval([[1, 2, 3, 4], [1, 2, 3, 4]]) == 1.0


def test_ranking_respects_failures():
    a = (
        "a",
        {
            "verdict": "FAIL",
            "counts": {"head_assertion_failures": 1},
            "pairwise": {"head_win_rate": 0.9},
            "metrics": {"score": {"head": {"mean": 9, "ci_lower": 8, "ci_upper": 10}}},
        },
    )
    b = (
        "b",
        {
            "verdict": "PASS",
            "counts": {"head_assertion_failures": 0},
            "pairwise": {"head_win_rate": 0.4},
            "metrics": {"score": {"head": {"mean": 7, "ci_lower": 6, "ci_upper": 8}}},
        },
    )
    rows = rank_results([a, b])
    assert rows[0]["name"] == "b"
