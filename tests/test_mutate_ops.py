from gitgrounded.config.schema import MutationCfg
from gitgrounded.coverage.extract import Behavior
from gitgrounded.coverage.mutate import generate_mutants, negate, swap_value, weaken


def test_operators():
    assert negate("Always cite the policy.") == "Never cite the policy."
    assert negate("Do not invent facts.") == "Do invent facts."
    assert weaken("You must reply in JSON.") == "You may reply in JSON."
    assert swap_value("Refunds within 30 days.") == "Refunds within 60 days."
    assert swap_value("No numbers here.") is None


def test_generate_mutants_on_prompt():
    prompt = "You are a bot.\n\nAlways cite the policy line. Never reveal secrets.\n"
    behaviors = [
        Behavior(id="b1", kind="rule_must", statement="cite", source_ids=["p.txt#main:2"], severity="critical"),
        Behavior(
            id="b2", kind="rule_must_not", statement="no secrets", source_ids=["p.txt#main:3"], severity="critical"
        ),
    ]
    muts = generate_mutants(MutationCfg(max_mutants=20), behaviors, {"p.txt": prompt}, "p.txt")
    ops = {m.operator for m in muts}
    assert {"delete_rule", "negate_rule", "weaken_rule"} <= ops
    deleted = next(m for m in muts if m.operator == "delete_rule" and m.behavior_ids == ["b1"])
    assert "cite" not in deleted.overrides["p.txt"]
    assert all(m.overrides["p.txt"] != prompt for m in muts)
