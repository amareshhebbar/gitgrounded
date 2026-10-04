import re
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

from gitgrounded.canonical import content_hash
from gitgrounded.config.schema import MutationCfg
from gitgrounded.coverage.extract import SEVERITY_RANK, Behavior
from gitgrounded.coverage.ingest import Sentence, split_sentences
from gitgrounded.jsonpath import jsonpath_set

RULE_KINDS = {
    "rule_must",
    "rule_must_not",
    "refusal",
    "format",
    "escalation",
    "tool_use",
    "persona",
    "knowledge",
    "capability",
}

NEGATIONS = [
    (re.compile(r"\bAlways\b"), "Never"),
    (re.compile(r"\balways\b"), "never"),
    (re.compile(r"\bNever\b"), "Always"),
    (re.compile(r"\bnever\b"), "always"),
    (re.compile(r"\bmust not\b"), "must"),
    (re.compile(r"\bmust\b"), "must not"),
    (re.compile(r"\bDo not\b"), "Do"),
    (re.compile(r"\bdo not\b"), "do"),
    (re.compile(r"\bDon't\b"), "Do"),
    (re.compile(r"\bdon't\b"), "do"),
    (re.compile(r"\bshould not\b"), "should"),
    (re.compile(r"\bshould\b"), "should not"),
    (re.compile(r"\bonly\b"), "not only"),
]

WEAKEN = [
    (re.compile(r"\bAlways\b"), "Usually"),
    (re.compile(r"\balways\b"), "usually"),
    (re.compile(r"\bNever\b"), "Rarely"),
    (re.compile(r"\bnever\b"), "rarely"),
    (re.compile(r"\bmust\b"), "may"),
    (re.compile(r"\bshould\b"), "could"),
    (re.compile(r"\bonly\b"), "preferably"),
    (re.compile(r"\bexactly\b"), "roughly"),
    (re.compile(r"\bstrictly\b"), "loosely"),
]

NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


@dataclass
class Mutant:
    id: str
    operator: str
    description: str
    behavior_ids: list[str]
    overrides: dict[str, str] = field(default_factory=dict)
    overlay: dict[str, Any] = field(default_factory=dict)
    diff_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("overrides")
        d["files"] = sorted(self.overrides)
        return d


def _apply_first(text: str, rules: list[tuple[re.Pattern, str]]) -> str | None:
    for pattern, repl in rules:
        if pattern.search(text):
            return pattern.sub(repl, text, count=1)
    return None


def negate(text: str) -> str:
    out = _apply_first(text, NEGATIONS)
    if out is not None:
        return out
    t = text.strip()
    return "Do not " + t[0].lower() + t[1:] if t else t


def weaken(text: str) -> str | None:
    return _apply_first(text, WEAKEN)


def swap_value(text: str) -> str | None:
    m = NUMBER.search(text)
    if not m:
        return None
    raw = m.group(1)
    value = float(raw)
    new = value * 2 if value >= 2 else value + 1
    new_s = str(int(new)) if new == int(new) and "." not in raw else f"{new:g}"
    return text[: m.start(1)] + new_s + text[m.end(1) :]


def _replace_span(content: str, s: Sentence, replacement: str) -> str:
    if content[s.start : s.end] == s.text or content[s.start : s.end].strip() == s.text:
        return content[: s.start] + replacement + content[s.end :]
    idx = content.find(s.text)
    if idx < 0:
        return content
    return content[:idx] + replacement + content[idx + len(s.text) :]


def _sections(content: str) -> list[tuple[int, int]]:
    blocks = []
    pos = 0
    for part in re.split(r"(\n\s*\n)", content):
        if part.strip() and not re.fullmatch(r"\n\s*\n", part):
            blocks.append((pos, pos + len(part)))
        pos += len(part)
    return blocks


def generate_mutants(
    cfg: MutationCfg, behaviors: list[Behavior], files: dict[str, str], target_file: str | None
) -> list[Mutant]:
    mutants: list[Mutant] = []
    seen: set[str] = set()

    def add(m: Mutant) -> None:
        sig = content_hash({"o": m.overrides, "v": m.overlay})
        if sig in seen:
            return
        for rel, content in m.overrides.items():
            if files.get(rel) == content:
                return
        seen.add(sig)
        m.id = f"m-{len(mutants) + 1:03d}-{m.operator}"
        mutants.append(m)

    if target_file and target_file in files:
        content = files[target_file]
        sents = {s.id: s for s in split_sentences(content, target_file, "prompt")}
        ordered = sorted(
            [b for b in behaviors if b.kind in RULE_KINDS and any(sid in sents for sid in b.source_ids)],
            key=lambda b: (-SEVERITY_RANK.get(b.severity, 1), b.id),
        )
        ops = [o for o in cfg.operators if o in ("delete_rule", "negate_rule", "weaken_rule", "swap_value")]
        for b in ordered:
            s = next(sents[sid] for sid in b.source_ids if sid in sents)
            for op in ops:
                if op == "delete_rule":
                    new = _replace_span(content, s, "")
                    desc = f"deleted: {s.text[:100]}"
                elif op == "negate_rule":
                    if b.kind not in ("rule_must", "rule_must_not", "refusal", "format", "escalation"):
                        continue
                    new = _replace_span(content, s, negate(s.text))
                    desc = f"negated: {s.text[:100]}"
                elif op == "weaken_rule":
                    w = weaken(s.text)
                    if w is None:
                        continue
                    new = _replace_span(content, s, w)
                    desc = f"weakened: {s.text[:100]}"
                else:
                    w = swap_value(s.text)
                    if w is None:
                        continue
                    new = _replace_span(content, s, w)
                    desc = f"changed a value: {s.text[:100]}"
                add(Mutant("", op, desc, [b.id], {target_file: new}, diff_hint=f"{op} on: {s.text}"))
        if "drop_section" in cfg.operators:
            for start, end in _sections(content):
                block = content[start:end]
                covered = [
                    b.id
                    for b in behaviors
                    if any(sid in sents and start <= sents[sid].start < end for sid in b.source_ids)
                ]
                if len(covered) >= 2:
                    add(
                        Mutant(
                            "",
                            "drop_section",
                            f"dropped section: {block.strip()[:80]}",
                            covered,
                            {target_file: content[:start] + content[end:]},
                            diff_hint=f"removed block: {block[:300]}",
                        )
                    )
    for b in behaviors:
        if b.kind != "knowledge":
            continue
        for sid in b.source_ids:
            rel = sid.split("#", 1)[0]
            if rel == target_file or rel not in files or "swap_value" not in cfg.operators:
                continue
            doc_sents = {s.id: s for s in split_sentences(files[rel], rel, "document")}
            s = doc_sents.get(sid)
            if s is None:
                continue
            w = swap_value(s.text)
            if w is None:
                continue
            add(
                Mutant(
                    "",
                    "swap_value",
                    f"changed a value in {rel}: {s.text[:100]}",
                    [b.id],
                    {rel: _replace_span(files[rel], s, w)},
                    diff_hint=f"document value changed: {s.text}",
                )
            )
            break
    if cfg.model_file and cfg.model_key and cfg.downgrade_to and cfg.model_file in files:
        data = yaml.safe_load(files[cfg.model_file]) or {}
        data = jsonpath_set(data, cfg.model_key, cfg.downgrade_to)
        add(
            Mutant(
                "",
                "model_downgrade",
                f"model set to {cfg.downgrade_to}",
                [b.id for b in behaviors],
                {cfg.model_file: yaml.safe_dump(data, sort_keys=False)},
                diff_hint=f"model changed to {cfg.downgrade_to}",
            )
        )
    return _round_robin(mutants, cfg.max_mutants)


def _round_robin(mutants: list[Mutant], limit: int) -> list[Mutant]:
    if len(mutants) <= limit:
        return mutants
    by_op: dict[str, list[Mutant]] = {}
    for m in mutants:
        by_op.setdefault(m.operator, []).append(m)
    out: list[Mutant] = []
    model = by_op.pop("model_downgrade", [])
    out += model[:1]
    queues = list(by_op.values())
    while len(out) < limit and any(queues):
        for q in queues:
            if q and len(out) < limit:
                out.append(q.pop(0))
    return out
