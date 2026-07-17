"""Login rate limiting (SEC-008) — uniform failures, no username oracle."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_LOCK = threading.Lock()
_FAILURES: dict[str, list[float]] = defaultdict(list)

# Window and threshold are intentionally modest for local/dev usability.
_WINDOW_SEC = 60.0
_MAX_FAILURES = 8


def _key(ip: str, username: str) -> str:
    return f"{(ip or 'unknown').strip()}|{(username or '').strip().lower()}"


def reset_login_throttle_for_tests() -> None:
    with _LOCK:
        _FAILURES.clear()


def check_login_allowed(ip: str, username: str, *, now: float | None = None) -> bool:
    """Return False when the IP+username pair is throttled."""
    current = time.time() if now is None else float(now)
    key = _key(ip, username)
    with _LOCK:
        stamps = [t for t in _FAILURES.get(key, []) if current - t <= _WINDOW_SEC]
        _FAILURES[key] = stamps
        return len(stamps) < _MAX_FAILURES


def record_login_failure(ip: str, username: str, *, now: float | None = None) -> None:
    current = time.time() if now is None else float(now)
    key = _key(ip, username)
    with _LOCK:
        stamps = [t for t in _FAILURES.get(key, []) if current - t <= _WINDOW_SEC]
        stamps.append(current)
        _FAILURES[key] = stamps


def clear_login_failures(ip: str, username: str) -> None:
    key = _key(ip, username)
    with _LOCK:
        _FAILURES.pop(key, None)
