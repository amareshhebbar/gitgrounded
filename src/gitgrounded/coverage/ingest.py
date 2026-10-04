import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from gitgrounded.config.schema import CoverageSources
from gitgrounded.project import Project

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
MAX_DOC_SENTENCES = 240


@dataclass
class Sentence:
    id: str
    text: str
    section: str
    file: str
    kind: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "main"


def split_sentences(text: str, file: str, kind: str) -> list[Sentence]:
    out: list[Sentence] = []
    section = "main"
    counters: dict[str, int] = {}
    offset = 0
    for line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        stripped = line.strip()
        if not stripped:
            continue
        m = HEADING.match(line)
        if m:
            section = _slug(m.group(2))
            continue
        bm = BULLET.match(line)
        body = line[bm.end() :] if bm else line.lstrip()
        body_start = line_start + (bm.end() if bm else len(line) - len(line.lstrip()))
        pieces = []
        pos = 0
        body_text = body.rstrip("\n")
        for part in SENTENCE_END.split(body_text):
            idx = body_text.find(part, pos)
            if idx < 0:
                idx = pos
            pieces.append((idx, part))
            pos = idx + len(part)
        for idx, part in pieces:
            part_clean = part.strip()
            if len(part_clean) < 3 or part_clean.startswith("{{"):
                continue
            counters[section] = counters.get(section, 0) + 1
            start = body_start + idx
            out.append(
                Sentence(
                    id=f"{file}#{section}:{counters[section]}",
                    text=part_clean,
                    section=section,
                    file=file,
                    kind=kind,
                    start=start,
                    end=start + len(part.rstrip()),
                )
            )
    return out


def tool_sentences(path: str, data: Any) -> list[Sentence]:
    tools = data.get("tools", data) if isinstance(data, dict) else data
    out = []
    for t in tools or []:
        name = t.get("name", "")
        schema = t.get("inputSchema") or t.get("input_schema") or t.get("parameters") or {}
        params = []
        for pname, p in (schema.get("properties") or {}).items():
            req = "required" if pname in (schema.get("required") or []) else "optional"
            params.append(f"{pname} ({p.get('type', 'any')}, {req}): {p.get('description', '')}")
        text = f"Tool {name}: {t.get('description', '')}" + (f" Parameters: {'; '.join(params)}" if params else "")
        out.append(
            Sentence(id=f"{path}#tool:{name}", text=text, section="tools", file=path, kind="tool", start=0, end=0)
        )
    return out


def _sample_document(sents: list[Sentence], limit: int) -> list[Sentence]:
    if len(sents) <= limit:
        return sents
    by_section: dict[str, list[Sentence]] = {}
    for s in sents:
        by_section.setdefault(s.section, []).append(s)
    per = max(1, limit // max(1, len(by_section)))
    out = []
    for group in by_section.values():
        step = max(1, len(group) // per)
        out += group[::step][:per]
    return out[:limit]


def read_source(project: Project, rel: str, files: dict[str, str] | None) -> str | None:
    if files and rel in files:
        return files[rel]
    p = project.resolve(rel)
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None


def ingest(
    project: Project,
    sources: CoverageSources,
    files: dict[str, str] | None = None,
    system_prompt_text: str | None = None,
) -> list[Sentence]:
    out: list[Sentence] = []
    if sources.system_prompt:
        text = read_source(project, sources.system_prompt, files)
        if text is not None:
            out += split_sentences(text, sources.system_prompt, "prompt")
    elif system_prompt_text and not sources.prompts:
        out += split_sentences(system_prompt_text, "system_prompt", "prompt")
    for rel in sources.prompts:
        text = read_source(project, rel, files)
        if text is not None:
            out += split_sentences(text, rel, "prompt")
    for doc in sources.documents:
        text = read_source(project, doc, files)
        if text is not None:
            out += _sample_document(split_sentences(text, doc, "document"), MAX_DOC_SENTENCES)
    for tool_file in sources.tools:
        text = read_source(project, tool_file, files)
        if text is not None:
            out += tool_sentences(tool_file, json.loads(text))
    return out


def sentences_by_id(sentences: list[Sentence]) -> dict[str, Sentence]:
    return {s.id: s for s in sentences}


def load_sources_text(project: Project, sources: CoverageSources) -> str:
    parts = []
    for rel in ([sources.system_prompt] if sources.system_prompt else []) + list(sources.documents):
        p = project.resolve(rel)
        if p.exists():
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n\n".join(parts)


def file_exists(project: Project, rel: str) -> bool:
    return Path(project.resolve(rel)).exists()
