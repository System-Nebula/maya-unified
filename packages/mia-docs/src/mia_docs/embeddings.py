"""Deterministic local embeddings (all-MiniLM-L6-v2, 384-d).

sentence-transformers pulls torch, so the model is lazy-loaded; when it is
unavailable (unit tests, minimal installs) a stable hash-based unit vector
stands in, mirroring maya-ingest's LocalEmbedder pattern.
"""

from __future__ import annotations

import hashlib
import os
from typing import Sequence

DIM = 384
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_model = None
_model_failed = False


def _load_model():
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    if os.getenv("MIA_DOCS_HASH_EMBED"):
        _model_failed = True
        return None
    try:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL_NAME)
    except Exception:
        _model_failed = True
    return _model


def _hash_vector(text: str) -> list[float]:
    # blake2b caps digest_size at 64 bytes; chain keyed digests to fill DIM*2
    data = text.encode("utf-8")
    buf = b""
    counter = 0
    while len(buf) < DIM * 2:
        buf += hashlib.blake2b(data, digest_size=64, salt=counter.to_bytes(8, "big")).digest()
        counter += 1
    buf = buf[: DIM * 2]
    raw = [int.from_bytes(buf[i : i + 2], "big") / 65535.0 - 0.5 for i in range(0, len(buf), 2)]
    norm = sum(x * x for x in raw) ** 0.5 or 1.0
    return [x / norm for x in raw]


def embed(texts: Sequence[str]) -> list[list[float]]:
    model = _load_model()
    if model is None:
        return [_hash_vector(t) for t in texts]
    return [list(map(float, v)) for v in model.encode(list(texts), normalize_embeddings=True)]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(x * x for x in b) ** 0.5 or 1.0
    return dot / (na * nb)


def recipe_embed_text(title: str, ingredient_names: list[str], steps: list[str]) -> str:
    """title + ingredient names + instructions — what the recipe *is*, not
    its formatting/metadata."""
    return "\n".join([title, ", ".join(ingredient_names), " ".join(steps)])
