"""Guest session cookie for room members."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

GUEST_SESSION_COOKIE = "maya_guest_session"
GUEST_SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _secret() -> bytes:
    return os.getenv("SESSION_SECRET", "dev-change-me-in-production").encode()


def sign_guest_session(member_id: str, room_id: str) -> str:
    payload = json.dumps(
        {"member_id": member_id, "room_id": room_id, "exp": int(time.time()) + GUEST_SESSION_MAX_AGE},
        separators=(",", ":"),
    )
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_guest_session(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if int(data.get("exp") or 0) < int(time.time()):
        return None
    if not data.get("member_id") or not data.get("room_id"):
        return None
    return data


def hash_guest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
