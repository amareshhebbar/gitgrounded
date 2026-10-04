from gitgrounded.config.schema import CoverageCfg

DEFAULT_DIMENSIONS: dict[str, list[str]] = {
    "style": ["terse", "verbose", "polite", "angry", "typo_heavy"],
    "language": ["en"],
    "difficulty": ["easy", "edge", "adversarial"],
    "adversary": [
        "none",
        "prompt_injection",
        "out_of_scope",
        "ambiguous",
        "conflicting_instruction",
        "missing_info",
        "multi_intent",
    ],
    "turns": ["single", "multi"],
}

RELEVANT: dict[str, set[str]] = {
    "format": {"style", "language", "turns", "difficulty"},
    "refusal": {"style", "language", "adversary", "difficulty"},
    "rule_must_not": {"style", "language", "difficulty", "adversary", "turns"},
    "rule_must": {"style", "language", "difficulty", "adversary", "turns"},
    "persona": {"style", "language", "adversary"},
    "knowledge": {"style", "language", "difficulty", "turns"},
    "capability": {"style", "language", "difficulty", "adversary", "turns"},
    "tool_use": {"style", "difficulty", "adversary"},
    "escalation": {"style", "difficulty", "adversary"},
}

DESCRIPTIONS = {
    "terse": "very short message, few words",
    "verbose": "long message with background details",
    "polite": "polite and formal",
    "angry": "frustrated, emotional, possibly rude",
    "typo_heavy": "many typos and missing punctuation",
    "all_caps": "written in capital letters",
    "code_mixed": "mixes English with another language",
    "code_mixed_hinglish": "Hinglish, Hindi words written in Latin script mixed with English",
    "easy": "straightforward, typical case",
    "edge": "boundary value or unusual but valid case",
    "adversarial": "tries to make the assistant break a rule",
    "none": "no adversarial element",
    "prompt_injection": "contains an instruction trying to override the system prompt",
    "out_of_scope": "asks for something outside the assistant's scope",
    "ambiguous": "ambiguous wording that needs clarification",
    "conflicting_instruction": "asks the assistant to ignore one of its rules",
    "missing_info": "omits information needed to answer",
    "multi_intent": "contains two or more requests",
    "single": "one user message",
    "multi": "short multi turn conversation ending with the key request",
}


def build_dimensions(cfg: CoverageCfg) -> dict[str, list[str]]:
    dims = {k: list(v) for k, v in DEFAULT_DIMENSIONS.items()} if cfg.use_default_dimensions else {}
    for k, v in cfg.dimensions.items():
        dims[k] = list(v)
    return {k: v for k, v in dims.items() if v}


def dims_for_kind(kind: str, dims: dict[str, list[str]], refusal_needs_adversary: bool = True) -> dict[str, list[str]]:
    relevant = RELEVANT.get(kind, set(dims))
    out = {}
    for name, values in dims.items():
        if name in DEFAULT_DIMENSIONS and name not in relevant:
            out[name] = [values[0]]
        else:
            out[name] = list(values)
    if kind == "refusal" and refusal_needs_adversary and "adversary" in out:
        filtered = [v for v in out["adversary"] if v != "none"]
        out["adversary"] = filtered or out["adversary"]
    return out


def describe(value: str) -> str:
    return DESCRIPTIONS.get(value, value.replace("_", " "))
