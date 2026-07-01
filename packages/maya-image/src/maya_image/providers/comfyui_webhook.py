"""Verify comfyui-api webhook_v2 HMAC signatures (src/event-emitters.ts)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os


def resolve_webhook_secret() -> str | None:
    return os.getenv("COMFYUI_WEBHOOK_SECRET")


def verify_webhook_v2(
    body: bytes,
    *,
    webhook_id: str | None,
    timestamp: str | None,
    signature_header: str | None,
    secret_b64: str | None = None,
) -> bool:
    """Return True when ``webhook-signature`` matches comfyui-api v2 signing."""
    secret = secret_b64 or resolve_webhook_secret()
    if not secret or not webhook_id or not timestamp or not signature_header:
        return False
    if not signature_header.startswith("v1,"):
        return False
    received_sig = signature_header[3:]
    signed_content = f"{webhook_id}.{timestamp}.{body.decode()}"
    try:
        key = base64.b64decode(secret)
    except Exception:
        return False
    expected_sig = base64.b64encode(
        hmac.new(key, signed_content.encode(), hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected_sig, received_sig)
