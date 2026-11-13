"""Embeddings: turn text into a list of numbers so we can search by meaning.

- SentenceTransformerEmbedder: the real, multilingual model (runs locally, free).
  The first time the model is downloaded (~470 MB), after that it works offline.
- HashingEmbedder: simple replacement without a model, for tests and emergencies.
  It only finds identical words, no synonyms.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence

from ..models import PartBase


class Embedder(Protocol):
    dim: int

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def part_text(part: PartBase) -> str:
    """The text we embed per part."""
    pieces = [
        part.name,
        part.description,
        "category: " + part.category_path.replace("/", " > ").replace("-", " "),
    ]
    if part.sectors:
        pieces.append("sectors: " + ", ".join(part.sectors))
    if part.material:
        pieces.append("material: " + part.material)
    if part.color:
        pieces.append("color: " + part.color)
    if part.standards:
        pieces.append("standards: " + ", ".join(part.standards))
    tags = [t for t in part.tags if t != "needs-review"]
    if tags:
        pieces.append("keywords: " + ", ".join(tags))
    return ". ".join(p for p in pieces if p)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, dim: int):
        self.model_name = model_name
        self.dim = dim
        self._model = None
        # e5 models expect these prefixes
        self._e5 = "e5" in model_name.lower()

    def _load(self):
        if self._model is None:
            import os

            # Windows has no symlinks in the cache by default: works fine, only a warning
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            from sentence_transformers import SentenceTransformer

            try:  # first from the local cache: faster and without an internet check
                self._model = SentenceTransformer(self.model_name, local_files_only=True)
            except Exception:  # noqa: BLE001 - not downloaded yet
                self._model = SentenceTransformer(self.model_name)
            get_dim = getattr(self._model, "get_embedding_dimension", None) \
                or self._model.get_sentence_embedding_dimension
            real_dim = get_dim()
            if real_dim != self.dim:
                raise ValueError(
                    f"Model {self.model_name} gives {real_dim} numbers, PARTSFINDER_EMBEDDING_DIM is {self.dim}"
                )
        return self._model

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        vecs = self._load().encode(list(texts), normalize_embeddings=True, batch_size=32,
                                   show_progress_bar=False)
        return [list(map(float, v)) for v in vecs]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([("passage: " if self._e5 else "") + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([("query: " if self._e5 else "") + text])[0]


class HashingEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        words = re.findall(r"[a-z0-9]+", text.lower())
        grams = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
        for g in grams:
            h = int.from_bytes(hashlib.md5(g.encode()).digest()[:8], "little")
            v[h % self.dim] += -1.0 if (h >> 63) & 1 else 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)
