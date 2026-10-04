from hypothesis import given, settings
from hypothesis import strategies as st

from gitgrounded.config.schema import CoverageCfg
from gitgrounded.coverage.extract import Behavior
from gitgrounded.coverage.planner import allocate, covering_array, plan, tuple_coverage


@settings(max_examples=30, deadline=None)
@given(st.dictionaries(st.sampled_from(list("abcdef")), st.integers(1, 5), min_size=1, max_size=5))
def test_covering_array_covers_all_pairs(sizes):
    params = {k: [f"{k}{i}" for i in range(n)] for k, n in sizes.items()}
    rows = covering_array(params, 2)
    covered, required = tuple_coverage(rows, params, 2)
    assert covered == required


def test_much_smaller_than_cartesian():
    params = {k: [str(i) for i in range(5)] for k in "abcdef"}
    rows = covering_array(params, 2)
    assert len(rows) < 60
    assert rows[0] == {k: "0" for k in "abcdef"}


def test_strength_three():
    params = {k: ["x", "y", "z"] for k in "abcd"}
    rows = covering_array(params, 3)
    covered, required = tuple_coverage(rows, params, 3)
    assert covered == required


def test_allocation_weights_severity():
    bs = [Behavior(id="a", statement="a", severity="critical"), Behavior(id="b", statement="b", severity="minor")]
    alloc = allocate(bs, 40, 2)
    assert alloc["a"] > alloc["b"] >= 2


def test_plan_has_baseline_cell():
    bs = [Behavior(id="r", kind="refusal", statement="refuse off topic", severity="major")]
    plans = plan(
        bs,
        {"style": ["terse", "angry"], "adversary": ["none", "out_of_scope", "prompt_injection"]},
        CoverageCfg(budget_cases=6),
    )
    cells = plans[0].cells
    assert cells[0].baseline
    assert all(c.values["adversary"] != "none" for c in cells)
