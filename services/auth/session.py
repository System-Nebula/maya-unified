"""Signed session cookies for local operator sessions (SEC-008).

Reuses SESSION_SECRET when set. For local loopback profile, a random secret is
written once under DATA_DIR when unset. Operator profile refuses weak secrets
at startup (see services.deployment.profile).
"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from services.auth.session_version import get_session_version
from services.paths import DATA_DIR

OPERATOR_SESSION_COOKIE = "maya_op_session"
OPERATOR_SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days
_LOCAL_SECRET_NAME = "session_secret"


def local_session_secret_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / _LOCAL_SECRET_NAME


def ensure_local_session_secret(*, environ: dict[str, str] | None = None) -> str:
    """Return SESSION_SECRET, generating a local file secret when unset."""
    env = environ if environ is not None else os.environ
    existing = str(env.get("SESSION_SECRET", "") or "").strip()
    if existing:
        return existing
    path = local_session_secret_path()
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            env["SESSION_SECRET"] = text
            return text
    generated = secrets.token_urlsafe(32)
    path.write_text(generated + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    env["SESSION_SECRET"] = generated
    return generated


def _serializer() -> URLSafeTimedSerializer:
    secret = str(os.getenv("SESSION_SECRET", "") or "").strip()
    if not secret:
        # Prefer local file over public fallback (SEC-008).
        path = local_session_secret_path()
        if path.is_file():
            secret = path.read_text(encoding="utf-8").strip()
    if not secret:
        secret = os.getenv("SESSION_SECRET_FALLBACK", "dev-insecure-change-me")
    return URLSafeTimedSerializer(secret, salt="maya-operator-session")


def sign_operator_session(operator_id: str, *, session_version: int | None = None) -> str:
    version = (
        int(session_version)
        if session_version is not None
        else get_session_version(operator_id)
    )
    payload = {
        "operator_id": operator_id,
        "iat": int(time.time()),
        "sv": version,
    }
    return _serializer().dumps(payload)


def verify_operator_session(token: str) -> dict[str, Any] | None:
    try:
        payload = _serializer().loads(token, max_age=OPERATOR_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or not payload.get("operator_id"):
        return None
    oid = str(payload["operator_id"])
    expected = get_session_version(oid)
    try:
        got = int(payload.get("sv", 0))
    except (TypeError, ValueError):
        got = 0
    if got != expected:
        return None
    return payload


def session_cookie_secure() -> bool:
    """True when SESSION_COOKIE_SECURE=1 (set behind TLS proxy)."""
    return os.getenv("SESSION_COOKIE_SECURE", "0").strip().lower() in ("1", "true", "yes")
