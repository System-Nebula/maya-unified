"""Mailgun webhook signature + replay protection (SEC-007)."""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import OrderedDict

from fastapi import HTTPException

_DEFAULT_MAX_AGE_SEC = 900  # 15 minutes
_REPLAY_LOCK = threading.Lock()
_SEEN_TOKENS: OrderedDict[str, float] = OrderedDict()
_MAX_SEEN = 4096


def webhook_secret(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    return str(env.get("DISCOVER_INBOX_WEBHOOK_SECRET", "") or "").strip()


def _remember_token(token: str, *, now: float) -> None:
    with _REPLAY_LOCK:
        if token in _SEEN_TOKENS:
            raise HTTPException(status_code=401, detail="replayed mailgun token")
        _SEEN_TOKENS[token] = now
        while len(_SEEN_TOKENS) > _MAX_SEEN:
            _SEEN_TOKENS.popitem(last=False)
        # Drop expired
        cutoff = now - _DEFAULT_MAX_AGE_SEC
        while _SEEN_TOKENS and next(iter(_SEEN_TOKENS.values())) < cutoff:
            _SEEN_TOKENS.popitem(last=False)


def reset_replay_cache_for_tests() -> None:
    with _REPLAY_LOCK:
        _SEEN_TOKENS.clear()


def verify_mailgun_signature(
    token: str | None,
    timestamp: str | None,
    signature: str | None,
    *,
    secret: str | None = None,
    now: float | None = None,
    max_age_sec: int = _DEFAULT_MAX_AGE_SEC,
) -> None:
    """Fail closed when secret missing; verify HMAC, freshness, and replay."""
    sec = (secret if secret is not None else webhook_secret()).strip()
    if not sec:
        raise HTTPException(
            status_code=503,
            detail="discover inbox webhook disabled (DISCOVER_INBOX_WEBHOOK_SECRET unset)",
        )
    if not token or not timestamp or not signature:
        raise HTTPException(status_code=401, detail="missing mailgun signature")

    try:
        ts = int(str(timestamp).strip())
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid mailgun timestamp") from exc

    current = time.time() if now is None else float(now)
    if abs(current - ts) > max_age_sec:
        raise HTTPException(status_code=401, detail="stale mailgun timestamp")

    digest = hmac.new(
        sec.encode(),
        f"{timestamp}{token}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(digest, signature):
        raise HTTPException(status_code=401, detail="invalid mailgun signature")

    _remember_token(str(token), now=current)
