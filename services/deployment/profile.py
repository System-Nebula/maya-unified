"""Deployment profile + bind-host policy (SEC-001).

Profiles:

- ``local`` (default): loopback only; skip public platform/webhook mounts.
- ``operator``: authenticated dashboard; host must be explicit when non-loopback;
  weak session secrets refused on non-loopback binds.
- ``public``: reserved for a separate public-safe app composition (this gateway
  still refuses to start as a full public voice/operator surface).
"""

from __future__ import annotations

import ipaddress
import os
from typing import Iterable

VALID_PROFILES = frozenset({"local", "operator", "public"})

# Known insecure defaults that must never back a non-loopback operator bind.
_WEAK_SESSION_SECRETS = frozenset(
    {
        "",
        "dev-insecure-change-me",
        "changeme",
        "change-me",
        "change-me-in-production",
        "secret",
        "password",
        "maya",
        "maya-secret",
    }
)


def resolve_maya_profile(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    raw = str(env.get("MAYA_PROFILE", "local") or "local").strip().lower()
    if raw not in VALID_PROFILES:
        raise RuntimeError(
            f"Invalid MAYA_PROFILE={raw!r}; expected one of: "
            + ", ".join(sorted(VALID_PROFILES))
        )
    return raw


def default_host_for_profile(profile: str) -> str:
    if profile == "local":
        return "127.0.0.1"
    return "0.0.0.0"


def resolve_bind_host(
    *,
    profile: str | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    env = environ if environ is not None else os.environ
    prof = profile or resolve_maya_profile(env)
    default = default_host_for_profile(prof)
    return str(env.get("HOST", default) or default).strip() or default


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    if h in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def allow_non_loopback_override(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return str(env.get("MAYA_ALLOW_NON_LOOPBACK", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def session_secret_value(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    secret = str(env.get("SESSION_SECRET", "") or "").strip()
    if secret:
        return secret
    return str(env.get("SESSION_SECRET_FALLBACK", "dev-insecure-change-me") or "").strip()


def is_weak_session_secret(secret: str) -> bool:
    s = (secret or "").strip()
    if s.lower() in _WEAK_SESSION_SECRETS:
        return True
    return len(s) < 16


def should_mount_public_platform_routes(profile: str | None = None) -> bool:
    """Public arena/discover/webhook-style platform routers — not for local."""
    prof = profile or resolve_maya_profile()
    return prof in {"operator", "public"}


def validate_startup_bind(
    *,
    profile: str | None = None,
    host: str | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return ``(profile, host)`` or raise ``RuntimeError`` on unsafe config."""
    env = environ if environ is not None else os.environ
    env = os.environ if environ is None else dict(environ)

    prof = profile or resolve_maya_profile(env)
    bind = host if host is not None else resolve_bind_host(profile=prof, environ=env)

    if prof == "public":
        raise RuntimeError(
            "MAYA_PROFILE=public is reserved for a separate public-safe app. "
            "Use MAYA_PROFILE=local (loopback) or MAYA_PROFILE=operator."
        )

    if prof == "local" and not is_loopback_host(bind):
        if not allow_non_loopback_override(env):
            raise RuntimeError(
                f"MAYA_PROFILE=local refuses non-loopback HOST={bind!r}. "
                "Bind 127.0.0.1/::1, or set MAYA_ALLOW_NON_LOOPBACK=1 to override "
                "(unsafe)."
            )

    # SEC-008: local loopback may generate a one-time secret file when unset.
    if prof == "local" and is_loopback_host(bind):
        from services.auth.session import ensure_local_session_secret

        ensure_local_session_secret(environ=env)

    secret = session_secret_value(env)
    # Operator profile always requires a strong secret (any bind).
    # Non-loopback binds always require a strong secret.
    if prof == "operator" or not is_loopback_host(bind):
        if is_weak_session_secret(secret):
            raise RuntimeError(
                f"MAYA_PROFILE={prof} HOST={bind!r} requires a strong SESSION_SECRET "
                "(set SESSION_SECRET to a random value of at least 16 characters)."
            )

    return prof, bind
