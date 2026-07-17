"""Per-operator session version for invalidation after password/ban (SEC-008)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from services.paths import DATA_DIR

_LOCK = threading.Lock()
_CACHE: dict[str, int] | None = None


def _path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "operator_session_versions.json"


def _load() -> dict[str, int]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _path()
    if not path.is_file():
        _CACHE = {}
        return _CACHE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        _CACHE = {}
        return _CACHE
    out: dict[str, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
    _CACHE = out
    return _CACHE


def _save(data: dict[str, int]) -> None:
    global _CACHE
    _CACHE = dict(data)
    path = _path()
    path.write_text(json.dumps(_CACHE, indent=2), encoding="utf-8")


def get_session_version(operator_id: str) -> int:
    oid = str(operator_id or "").strip()
    if not oid:
        return 0
    with _LOCK:
        return int(_load().get(oid, 0))


def bump_session_version(operator_id: str) -> int:
    oid = str(operator_id or "").strip()
    if not oid:
        return 0
    with _LOCK:
        data = _load()
        data[oid] = int(data.get(oid, 0)) + 1
        _save(data)
        return data[oid]


def reset_session_versions_for_tests() -> None:
    global _CACHE
    with _LOCK:
        _CACHE = {}
        path = _path()
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
