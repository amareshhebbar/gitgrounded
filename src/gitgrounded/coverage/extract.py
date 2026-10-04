import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gitgrounded.canonical import content_hash
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.coverage.ingest import Sentence
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.store.cache import Cache

BehaviorKind = Literal[
    "capability", "rule_must", "rule_must_not", "format", "persona", "refusal", "tool_use", "escalation", "knowledge"
]
SEVERITY_RANK = {"critical": 3, "major": 2, "minor": 1}

EXTRACT_SYSTEM = """You convert an AI application's specification into a list of atomic, testable behaviors.
You receive numbered source sentences, each with an id. Produce one behavior per distinct testable requirement or capability.
Rules:
- Atomic: one behavior tests one thing. Split compound sentences.
- Testable: "observable" must say how a reviewer recognizes a correct response from the output alone.
- Traceable: "source_ids" must list the ids of the sentences the behavior comes from. Never invent requirements that the sentences do not state.
- kind is one of: capability, rule_must, rule_must_not, format, persona, refusal, tool_use, escalation, knowledge.
- severity: critical if breaking it harms users, violates policy, breaks parsing or leaks data; major if it degrades the answer; minor otherwise.
- triggers: 2 to 5 short phrases describing user inputs that make this behavior matter.
Return JSON: {"behaviors": [{"kind": "...", "statement": "...", "source_ids": ["..."], "triggers": ["..."], "observable": "...", "severity": "critical|major|minor"}]}"""

KNOWLEDGE_SYSTEM = """You read reference documents that an AI application must answer from. Produce testable knowledge behaviors: facts, limits, numbers, conditions and exceptions a user could ask about.
Group closely related facts into one behavior, but keep every number, deadline and exception testable. Use kind "knowledge".
Each behavior must cite the source sentence ids it comes from in "source_ids".
Return JSON: {"behaviors": [{"kind": "knowledge", "statement": "...", "source_ids": ["..."], "triggers": ["..."], "observable": "...", "severity": "critical|major|minor"}]}"""

IMPLICIT_SYSTEM = """You are a senior QA engineer for LLM applications. Given a system prompt and the behaviors already extracted from it, list the IMPLICIT behaviors a production assistant with this prompt must also have but that are not explicitly written: handling out of scope requests, prompt injection, ambiguous or incomplete requests, conflicting user instructions, multiple intents in one message, sensitive data, and language or tone shifts.
Only include behaviors that clearly follow from the prompt's purpose. Do not repeat existing behaviors.
Return JSON: {"behaviors": [{"kind": "...", "statement": "...", "source_ids": [], "triggers": ["..."], "observable": "...", "severity": "critical|major|minor"}]}"""


class Behavior(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    kind: BehaviorKind = "capability"
    statement: str
    source_ids: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    observable: str = ""
    severity: Literal["critical", "major", "minor"] = "major"
    implicit: bool = False
    source_text: str = ""

    def key(self) -> str:
        return content_hash({"kind": self.kind, "statement": _norm(self.statement)})[:10]

    def fingerprint(self) -> str:
        return content_hash({"key": self.key(), "source": _norm(self.source_text)})[:16]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _coerce(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = raw.get("behaviors", [])
    out = []
    for b in raw or []:
        if not isinstance(b, dict) or not b.get("statement"):
            continue
        kind = b.get("kind", "capability")
        if kind not in BehaviorKind.__args__:
            kind = "capability"
        sev = b.get("severity", "major")
        if sev not in SEVERITY_RANK:
            sev = "major"
        out.append({**b, "kind": kind, "severity": sev})
    return out


def _call(
    provider_cfg: ProviderCfg, cache: Cache, system: str, payload: dict[str, Any], task: str, meta: dict[str, Any]
) -> list[dict[str, Any]]:
    key = cache.key(task, provider_cfg.model_dump(mode="json"), system, payload)
    hit = cache.get("coverage", key)
    if hit is not None:
        return hit
    provider = build_provider(provider_cfg)
    data, _ = complete_json(provider, system, json.dumps(payload, ensure_ascii=False), task=task, meta=meta)
    rows = _coerce(data)
    cache.set("coverage", key, rows)
    return rows


def _chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def extract_behaviors(
    provider_cfg: ProviderCfg,
    cache: Cache,
    sentences: list[Sentence],
    embedder=None,
    implicit: bool = True,
    dedupe_threshold: float = 0.92,
) -> list[Behavior]:
    by_id = {s.id: s for s in sentences}
    raw: list[dict[str, Any]] = []
    groups: dict[str, list[Sentence]] = {"prompt": [], "document": [], "tool": []}
    for s in sentences:
        groups.setdefault(s.kind, []).append(s)
    for kind, system in (("prompt", EXTRACT_SYSTEM), ("tool", EXTRACT_SYSTEM), ("document", KNOWLEDGE_SYSTEM)):
        for chunk in _chunks(groups.get(kind, []), 40):
            payload = {"sentences": [{"id": s.id, "text": s.text, "section": s.section} for s in chunk]}
            raw += _call(
                provider_cfg,
                cache,
                system,
                payload,
                "extract_behaviors",
                {"sentences": payload["sentences"], "kind": kind},
            )
    behaviors: list[Behavior] = []
    for b in raw:
        valid = [sid for sid in b.get("source_ids", []) if sid in by_id]
        if not valid:
            continue
        beh = Behavior.model_validate({**b, "source_ids": valid})
        beh.source_text = " ".join(by_id[sid].text for sid in valid)
        behaviors.append(beh)
    if implicit and groups.get("prompt"):
        prompt_text = " ".join(s.text for s in groups["prompt"])
        payload = {"system_prompt": prompt_text[:20000], "existing": [b.statement for b in behaviors]}
        for b in _call(
            provider_cfg,
            cache,
            IMPLICIT_SYSTEM,
            payload,
            "implicit_behaviors",
            {"existing": payload["existing"], "prompt": prompt_text},
        ):
            beh = Behavior.model_validate({**b, "source_ids": []})
            beh.implicit = True
            behaviors.append(beh)
    behaviors = dedupe(behaviors, embedder, dedupe_threshold, make_confirmer(provider_cfg, cache))
    for b in behaviors:
        b.id = f"b-{b.key()}"
    seen: set[str] = set()
    unique = []
    for b in behaviors:
        if b.id not in seen:
            seen.add(b.id)
            unique.append(b)
    return unique


MERGE_SYSTEM = """You decide whether two behaviors extracted from an AI application's specification test exactly the same requirement.
Return JSON: {"same": true} only if a single test would check both; otherwise {"same": false}."""


def make_confirmer(provider_cfg: ProviderCfg, cache: Cache):
    def confirm(a: Behavior, b: Behavior) -> bool:
        payload = {"a": a.statement, "b": b.statement}
        key = cache.key("merge", provider_cfg.model_dump(mode="json"), payload)
        hit = cache.get("coverage", key)
        if hit is None:
            data, _ = complete_json(
                build_provider(provider_cfg), MERGE_SYSTEM, json.dumps(payload), task="merge_check", meta=payload
            )
            hit = bool(data.get("same")) if isinstance(data, dict) else False
            cache.set("coverage", key, hit)
        return bool(hit)

    return confirm


def dedupe(
    behaviors: list[Behavior], embedder, threshold: float, confirm=None, confirm_floor: float = 0.85
) -> list[Behavior]:
    if embedder is None or len(behaviors) < 2:
        return behaviors
    vecs = embedder.embed([f"{b.kind}: {b.statement}" for b in behaviors])
    sims = vecs @ vecs.T
    keep: list[int] = []
    merged_into: dict[int, int] = {}
    for i in range(len(behaviors)):
        target = None
        for j in keep:
            if behaviors[i].kind != behaviors[j].kind:
                continue
            if sims[i, j] >= threshold or (
                confirm is not None and sims[i, j] >= confirm_floor and confirm(behaviors[j], behaviors[i])
            ):
                target = j
                break
        if target is None:
            keep.append(i)
        else:
            merged_into[i] = target
    for i, j in merged_into.items():
        a, b = behaviors[j], behaviors[i]
        a.source_ids = sorted(set(a.source_ids) | set(b.source_ids))
        if SEVERITY_RANK[b.severity] > SEVERITY_RANK[a.severity]:
            a.severity = b.severity
        a.triggers = list(dict.fromkeys(a.triggers + b.triggers))[:6]
        if b.source_text and b.source_text not in a.source_text:
            a.source_text = (a.source_text + " " + b.source_text).strip()
    return [behaviors[i] for i in keep]
