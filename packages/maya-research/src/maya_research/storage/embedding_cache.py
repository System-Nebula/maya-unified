"""Embedding helpers for prior-art recall and browser history cache."""

from __future__ import annotations

import hashlib
import os
from typing import Sequence

Vector = list[float]


class Embedder:
    DIM = 768

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vector(t) for t in texts]

    @classmethod
    def _hash_vector(cls, text: str) -> Vector:
        h = hashlib.blake2b(text.encode("utf-8"), digest_size=cls.DIM * 2).digest()
        raw = [int.from_bytes(h[i : i + 2], "big") / 65535.0 - 0.5 for i in range(0, len(h), 2)]
        norm = sum(x * x for x in raw) ** 0.5 or 1.0
        return [x / norm for x in raw]


def cosine_similarity(a: Vector, b: Vector) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def get_embedder() -> Embedder:
    backend = os.getenv("EMBED_BACKEND", "local")
    if backend == "nomic":
        return NomicEmbedder()
    return Embedder()


class NomicEmbedder(Embedder):
    def __init__(self) -> None:
        self._api_key = os.getenv("NOMIC_API_KEY")

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        import httpx

        if not self._api_key:
            return await super().embed(texts)
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api-atlas.nomic.ai/v1/embedding/text",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"texts": list(texts), "model": "nomic-embed-text-v1.5"},
            )
            resp.raise_for_status()
            return [list(map(float, e)) for e in resp.json()["embeddings"]]
