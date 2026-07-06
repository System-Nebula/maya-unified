"""SeaweedFS / S3-compatible object uploads for browser captures."""

from __future__ import annotations

import hashlib
import logging

import httpx

from services.browser.config import ASSET_EXTENSIONS, S3_BUCKET, S3_ENDPOINT

log = logging.getLogger(__name__)


def object_key(capture_id: str, kind: str) -> str:
    ext = ASSET_EXTENSIONS.get(kind, "bin")
    return f"browser/pages/{capture_id}/{kind}.{ext}"


async def upload_capture_asset(
    http_client: httpx.AsyncClient,
    capture_id: str,
    kind: str,
    raw: bytes,
    mime_type: str,
) -> dict:
    """Upload bytes to object store; return stored asset descriptor."""
    key = object_key(capture_id, kind)
    url = f"{S3_ENDPOINT}/{S3_BUCKET}/{key}"

    resp = await http_client.put(
        url,
        content=raw,
        headers={"Content-Type": mime_type},
        timeout=30.0,
    )
    resp.raise_for_status()

    return {
        "kind": kind,
        "key": key,
        "mime_type": mime_type,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
