"""HTML artifact storage — local filesystem with optional SeaweedFS upload."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx

_ARTIFACT_ROOT = Path(
    os.getenv(
        "ARTIFACT_STORE_DIR",
        str(
            Path(__file__).resolve().parents[1]
            / "static"
            / "artifacts"
        ),
    )
)
_SEAWEED_URL = os.getenv("SEAWEEDFS_URL", "").rstrip("/")
_STORE_MODE = os.getenv("ARTIFACT_STORE", "local").lower()


def artifact_public_url(artifact_id: str) -> str:
    return f"/api/discover/artifacts/{artifact_id}"


def artifact_key(artifact_id: str) -> str:
    return f"artifacts/{artifact_id}.html"


async def store_html(html: str, *, content_type: str = "text/html") -> tuple[str, str]:
    """Persist HTML and return (artifact_id, storage_key)."""
    artifact_id = str(uuid.uuid4())
    key = artifact_key(artifact_id)

    if _STORE_MODE == "seaweed" and _SEAWEED_URL:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_SEAWEED_URL}/{key}",
                content=html.encode("utf-8"),
                headers={"Content-Type": content_type},
            )
            resp.raise_for_status()
        return artifact_id, key

    dest = _ARTIFACT_ROOT / f"{artifact_id}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    return artifact_id, key


def load_html(artifact_id: str) -> tuple[bytes, str] | None:
    """Load artifact bytes and content type from local store."""
    path = _ARTIFACT_ROOT / f"{artifact_id}.html"
    if not path.is_file():
        return None
    return path.read_bytes(), "text/html; charset=utf-8"
