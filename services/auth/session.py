"""Signed session cookies for local operator sessions.

Reuses the same SESSION_SECRET env var as maya_gateway (different salt).
Cookie name: maya_op_session  (distinct from platform maya_session).
"""

from __future__ import annotations

import os
import time
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

OPERATOR_SESSION_COOKIE = "maya_op_session"
OPERATOR_SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SESSION_SECRET", "").strip()
    if not secret:
        secret = os.getenv("SESSION_SECRET_FALLBACK", "dev-insecure-change-me")
    return URLSafeTimedSerializer(secret, salt="maya-operator-session")


def sign_operator_session(operator_id: str) -> str:
    payload = {"operator_id": operator_id, "iat": int(time.time())}
    return _serializer().dumps(payload)


def verify_operator_session(token: str) -> dict[str, Any] | None:
    try:
        return _serializer().loads(token, max_age=OPERATOR_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def session_cookie_secure() -> bool:
    """True when SESSION_COOKIE_SECURE=1 (set behind TLS proxy)."""
    return os.getenv("SESSION_COOKIE_SECURE", "0").strip().lower() in ("1", "true", "yes")
