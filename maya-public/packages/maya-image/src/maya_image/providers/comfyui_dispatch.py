"""Cross-process dispatch context + idempotency guard for async image jobs.

When a job is submitted on the async (tier-3 / webhook) path the bot stores the
Discord + AGE-turn context needed to deliver the result from *another* process (the
gateway, which receives the comfyui-api webhook). Both the webhook handler and the
bot's poll loop may race to deliver; :func:`mark_dispatched` is an atomic SETNX guard
so exactly one of them posts to Discord and records the turn.

Backed by Redis/Valkey via :class:`CacheAdapter`, with an in-process fallback.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

_CONTEXT_PREFIX = "comfyui:dispatch:"
_GUARD_PREFIX = "comfyui:dispatched:"
_TTL = timedelta(hours=1)

# In-process fallbacks used when Redis (or the adapters package) is unavailable.
_context_fallback: dict[str, dict[str, Any]] = {}
_guard_fallback: set[str] = set()
_cache: Any = None


def _get_cache() -> Any:
    """Lazily build the Redis CacheAdapter; None if adapters/Redis aren't importable."""
    global _cache
    if _cache is None:
        try:
            from lib.adapters.adapters.cache import CacheAdapter

            _cache = CacheAdapter(default_ttl=_TTL)
        except Exception:
            return None
    return _cache


async def store_dispatch_context(comfyui_id: str, context: dict[str, Any]) -> None:
    """Persist the opaque Discord/turn context for ``comfyui_id``."""
    _context_fallback[comfyui_id] = context
    try:
        await _get_cache().set(f"{_CONTEXT_PREFIX}{comfyui_id}", context, ttl=_TTL)
    except Exception as exc:
        logger.warning("comfyui_dispatch_redis_unavailable", op="store", error=str(exc))


async def load_dispatch_context(comfyui_id: str) -> Optional[dict[str, Any]]:
    try:
        data = await _get_cache().get(f"{_CONTEXT_PREFIX}{comfyui_id}")
    except Exception as exc:
        logger.warning("comfyui_dispatch_redis_unavailable", op="load", error=str(exc))
        data = None
    if data is not None:
        return data
    return _context_fallback.get(comfyui_id)


async def mark_dispatched(comfyui_id: str) -> bool:
    """Atomically claim delivery for ``comfyui_id``. Returns True for the winner only."""
    try:
        won = await _get_cache().set_nx(f"{_GUARD_PREFIX}{comfyui_id}", True, ttl=_TTL)
        return bool(won)
    except Exception as exc:
        logger.warning("comfyui_dispatch_redis_unavailable", op="guard", error=str(exc))
        # Fallback: best-effort single-process guard.
        if comfyui_id in _guard_fallback:
            return False
        _guard_fallback.add(comfyui_id)
        return True
