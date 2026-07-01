"""Artifact storage for research reports and fetched pages."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import httpx


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def artifact_public_url(artifact_id: str) -> str:
    return f"/api/research/artifacts/{artifact_id}"


async def store_markdown(content: str, *, suffix: str = "md") -> tuple[str, str]:
    artifact_id = str(uuid.uuid4())
    key = f"research/{artifact_id}.{suffix}"
    store_mode = os.getenv("ARTIFACT_STORE", "local").lower()
    seaweed_url = os.getenv("SEAWEEDFS_URL", "").rstrip("/")

    if store_mode == "seaweed" and seaweed_url:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{seaweed_url}/{key}",
                content=content.encode("utf-8"),
                headers={"Content-Type": "text/markdown; charset=utf-8"},
            )
            resp.raise_for_status()
        return artifact_id, key

    root = Path(os.getenv("ARTIFACT_STORE_DIR", "/tmp/maya-research-artifacts"))
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{artifact_id}.{suffix}"
    dest.write_text(content, encoding="utf-8")
    return artifact_id, key


def load_markdown(artifact_id: str) -> tuple[bytes, str] | None:
    root = Path(os.getenv("ARTIFACT_STORE_DIR", "/tmp/maya-research-artifacts"))
    for suffix in ("md", "html"):
        path = root / f"{artifact_id}.{suffix}"
        if path.is_file():
            return path.read_bytes(), f"text/{suffix}; charset=utf-8"
    return None
