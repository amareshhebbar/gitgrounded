import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from gitgrounded.cases.model import Case, Expectation
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.coverage.extract import Behavior
from gitgrounded.providers.base import build_provider
from gitgrounded.providers.llm import complete_json
from gitgrounded.store.cache import Cache

PII_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("aadhaar", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?\d{1,3}[ -]?)?(?:\d[ -]?){9,11}\d(?!\d)")),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]

LABEL_SYSTEM = """You label a cluster of real user messages sent to an AI application. Return a short label (3 to 6 words) naming the shared intent.
Return JSON: {"label": "..."}"""


def _presidio(text: str) -> str | None:
    import os

    if os.environ.get("GITGROUNDED_PRESIDIO", "").lower() not in ("1", "true", "yes"):
        return None
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
    except ImportError:
        return None
    results = AnalyzerEngine().analyze(text=text, language="en")
    return AnonymizerEngine().anonymize(text=text, analyzer_results=results).text


def redact(text: str) -> str:
    text = _presidio(text) or text
    for name, pattern in PII_PATTERNS:
        text = pattern.sub(f"[{name}]", text)
    return text


def read_logs(path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    rows = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines() if path.suffix == ".jsonl" else None
    if lines is None:
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("items", data.get("data", []))
    else:
        items = [json.loads(line) for line in lines if line.strip()]
    for item in items[:limit]:
        if isinstance(item, str):
            rows.append({"input": item})
            continue
        inp = item.get("input") or item.get("message") or item.get("prompt") or item.get("question")
        if inp is None and isinstance(item.get("messages"), list):
            users = [m.get("content", "") for m in item["messages"] if m.get("role") == "user"]
            inp = users[-1] if users else None
        if isinstance(inp, dict):
            inp = inp.get("content") or json.dumps(inp)
        if inp:
            rows.append({"input": str(inp), "output": item.get("output")})
    return rows


def kmeans(vectors: np.ndarray, k: int, seed: int = 7, iters: int = 50) -> np.ndarray:
    n = len(vectors)
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    centers = [vectors[rng.integers(n)]]
    for _ in range(1, k):
        d = np.min([1 - vectors @ c for c in centers], axis=0)
        d = np.clip(d, 0, None)
        probs = d / d.sum() if d.sum() > 0 else np.full(n, 1 / n)
        centers.append(vectors[rng.choice(n, p=probs)])
    centers = np.asarray(centers)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        sims = vectors @ centers.T
        new = sims.argmax(axis=1)
        if np.array_equal(new, labels) and _ > 0:
            break
        labels = new
        for j in range(k):
            members = vectors[labels == j]
            if len(members):
                c = members.mean(axis=0)
                norm = np.linalg.norm(c)
                centers[j] = c / norm if norm else c
    return labels


def choose_k(vectors: np.ndarray, max_k: int = 12, seed: int = 7) -> int:
    n = len(vectors)
    if n < 6:
        return max(1, n // 2)
    best_k, best_score = 2, -1.0
    for k in range(2, min(max_k, n - 1) + 1):
        labels = kmeans(vectors, k, seed)
        score = _silhouette(vectors, labels)
        if score > best_score:
            best_k, best_score = k, score
    return best_k


def _silhouette(vectors: np.ndarray, labels: np.ndarray) -> float:
    dist = 1 - vectors @ vectors.T
    scores = []
    for i in range(len(vectors)):
        same = labels == labels[i]
        same[i] = False
        if not same.any():
            continue
        a = dist[i, same].mean()
        b = min((dist[i, labels == j].mean() for j in set(labels.tolist()) if j != labels[i]), default=a)
        scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return float(np.mean(scores)) if scores else -1.0


def analyze_logs(
    path: Path,
    behaviors: list[Behavior],
    embedder,
    provider_cfg: ProviderCfg,
    cache: Cache,
    max_clusters: int = 12,
    per_cluster: int = 3,
    match_threshold: float = 0.35,
) -> dict[str, Any]:
    rows = read_logs(path)
    if not rows:
        return {"clusters": [], "cases": [], "untested_traffic": [], "unseen_behaviors": []}
    texts = [redact(r["input"]) for r in rows]
    vecs = embedder.embed(texts)
    k = choose_k(vecs, max_clusters)
    labels = kmeans(vecs, k)
    beh_vecs = (
        embedder.embed([f"{b.statement} {' '.join(b.triggers)}" for b in behaviors])
        if behaviors
        else np.zeros((0, vecs.shape[1]))
    )
    provider = None
    clusters = []
    cases: list[Case] = []
    matched_behaviors: set[str] = set()
    for j in range(k):
        idx = np.where(labels == j)[0]
        if len(idx) == 0:
            continue
        centroid = vecs[idx].mean(axis=0)
        centroid /= np.linalg.norm(centroid) or 1.0
        reps = idx[np.argsort(-(vecs[idx] @ centroid))][:per_cluster]
        samples = [texts[i] for i in reps]
        key = cache.key("label", provider_cfg.model_dump(mode="json"), samples)
        label = cache.get("coverage", key)
        if label is None:
            provider = provider or build_provider(provider_cfg)
            data, _ = complete_json(
                provider,
                LABEL_SYSTEM,
                json.dumps({"messages": samples}, ensure_ascii=False),
                task="label_cluster",
                meta={"samples": samples},
            )
            label = str(data.get("label", f"cluster {j}")) if isinstance(data, dict) else f"cluster {j}"
            cache.set("coverage", key, label)
        best_b, best_s = None, -1.0
        if len(beh_vecs):
            sims = beh_vecs @ centroid
            bi = int(np.argmax(sims))
            best_b, best_s = behaviors[bi], float(sims[bi])
        mapped = best_b is not None and best_s >= match_threshold
        if mapped:
            matched_behaviors.add(best_b.id)
        clusters.append(
            {
                "cluster": j,
                "label": label,
                "size": int(len(idx)),
                "share": len(idx) / len(rows),
                "samples": samples,
                "behavior": best_b.id if mapped else None,
                "similarity": best_s,
            }
        )
        for n, i in enumerate(reps):
            exps = [Expectation(kind="must", text=best_b.statement, behavior_id=best_b.id)] if mapped else []
            cases.append(
                Case(
                    id=f"log-{j:02d}-{n + 1:02d}",
                    input=texts[i],
                    behaviors=[best_b.id] if mapped else [],
                    expectations=exps,
                    origin="log",
                    tags=["log", label],
                    meta={"cluster": j, "realistic": 1.0},
                )
            )
    untested = [c for c in clusters if c["behavior"] is None]
    unseen = [b.id for b in behaviors if b.id not in matched_behaviors and not b.implicit]
    return {
        "total_messages": len(rows),
        "clusters": clusters,
        "cases": cases,
        "untested_traffic": untested,
        "unseen_behaviors": unseen,
    }
