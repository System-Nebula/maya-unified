"""Pluggable embedder interface."""

from __future__ import annotations

import hashlib
import os
from typing import Protocol, Sequence


Vector = list[float]


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[Vector]: ...


class LocalEmbedder:
    """CPU-friendly fallback. Hashes text into a stable 768-d unit vector.

    Good enough for plumbing and tests; production deployments override via
    NomicEmbedder or another backend.
    """

    DIM = 768

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        return [self._hash_vector(t) for t in texts]

    @classmethod
    def _hash_vector(cls, text: str) -> Vector:
        h = hashlib.blake2b(text.encode("utf-8"), digest_size=cls.DIM * 2).digest()
        raw = [int.from_bytes(h[i : i + 2], "big") / 65535.0 - 0.5 for i in range(0, len(h), 2)]
        norm = sum(x * x for x in raw) ** 0.5 or 1.0
        return [x / norm for x in raw]


class NomicEmbedder:
    DIM = 768

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("NOMIC_API_KEY")

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        # Lazy import; nomic is optional.
        import httpx

        if not self._api_key:
            raise RuntimeError("NOMIC_API_KEY not set")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api-atlas.nomic.ai/v1/embedding/text",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"texts": list(texts), "model": "nomic-embed-text-v1.5"},
            )
            resp.raise_for_status()
            return [list(map(float, e)) for e in resp.json()["embeddings"]]


def get_embedder(backend: str = "local") -> Embedder:
    if backend == "nomic":
        return NomicEmbedder()
    return LocalEmbedder()
