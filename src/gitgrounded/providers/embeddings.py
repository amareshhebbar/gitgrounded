import hashlib
import os
import re
import threading

import numpy as np
import requests

from gitgrounded.config.schema import EmbeddingCfg
from gitgrounded.errors import ProviderError
from gitgrounded.providers.base import is_offline


class HashEmbedder:
    def __init__(self, dims: int = 512):
        self.dims = dims

    def _features(self, text: str) -> list[str]:
        text = (text or "").lower()
        words = re.findall(r"[a-z0-9]+", text)
        feats = list(words)
        feats += [f"{a}_{b}" for a, b in zip(words, words[1:])]
        for w in words:
            padded = f"#{w}#"
            feats += [padded[i : i + 3] for i in range(max(1, len(padded) - 2))]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for i, t in enumerate(texts):
            for f in self._features(t):
                d = hashlib.blake2b(f.encode(), digest_size=8).digest()
                idx = int.from_bytes(d[:4], "little") % self.dims
                sign = 1.0 if d[4] & 1 else -1.0
                out[i, idx] += sign
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


class LocalEmbedder:
    _models: dict[str, object] = {}
    _lock = threading.Lock()

    def __init__(self, model: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ProviderError("install gitgrounded[coverage] for local sentence-transformers embeddings") from e
        with self._lock:
            if model not in self._models:
                self._models[model] = SentenceTransformer(model)
        self.model = self._models[model]

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)


class OpenAICompatEmbedder:
    def __init__(self, cfg: EmbeddingCfg):
        self.cfg = cfg
        self.api_key = os.environ.get(cfg.api_key_env or "OPENAI_API_KEY", "")
        self.base_url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")

    def embed(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 128):
            batch = texts[i : i + 128]
            resp = requests.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.cfg.model, "input": batch},
                timeout=120,
            )
            resp.raise_for_status()
            out += [d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"])]
        arr = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms


def build_embedder(cfg: EmbeddingCfg):
    if is_offline() or cfg.provider == "hash":
        return HashEmbedder(cfg.dims)
    if cfg.provider == "local":
        return LocalEmbedder(cfg.model)
    return OpenAICompatEmbedder(cfg)


def cosine_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a @ b.T
