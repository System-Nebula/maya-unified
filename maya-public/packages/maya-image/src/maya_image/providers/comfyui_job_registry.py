"""Cross-process completion store for async comfyui-api webhook_v2 jobs.

comfyui-api has no ``GET /job/{id}`` endpoint, so Maya owns job correlation:
``ComfyUIIdeogramProvider.submit`` stores the comfyui ``id`` as provider_job_id and
the inbound webhook records completions here for :meth:`ComfyUIIdeogramProvider.poll`.

The gateway (which receives the webhook) and the Discord bot (which polls) run as
separate processes, so the store is backed by Redis/Valkey via :class:`CacheAdapter`.
A module-level dict is kept as a graceful-degrade fallback when Redis is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

_KEY_PREFIX = "comfyui:job:"
_TTL = timedelta(hours=1)

# In-process fallback used when Redis (or the adapters package) is unavailable.
_fallback: dict[str, "ComfyUIJobRecord"] = {}
_cache: Any = None


@dataclass
class ComfyUIJobRecord:
    status: str  # "submitted" | "completed" | "failed"
    payload: dict[str, Any] | None = None
    error: str | None = None


def _get_cache() -> Any:
    """Lazily build the Redis CacheAdapter. Returns None if adapters/Redis aren't
    importable (e.g. the Discord bot's venv) — callers fall back to the in-proc dict."""
    global _cache
    if _cache is None:
        try:
            from lib.adapters.adapters.cache import CacheAdapter

            _cache = CacheAdapter(default_ttl=_TTL)
        except Exception:
            return None
    return _cache


def _key(comfyui_id: str) -> str:
    return f"{_KEY_PREFIX}{comfyui_id}"


async def _store(comfyui_id: str, record: "ComfyUIJobRecord") -> None:
    _fallback[comfyui_id] = record
    try:
        await _get_cache().set(
            _key(comfyui_id),
            {"status": record.status, "payload": record.payload, "error": record.error},
            ttl=_TTL,
        )
    except Exception as exc:  # Redis down — fall back to in-process dict only.
        logger.warning("comfyui_registry_redis_unavailable", op="set", error=str(exc))


async def register_submitted(comfyui_id: str) -> None:
    await _store(comfyui_id, ComfyUIJobRecord(status="submitted"))


async def register_completion(comfyui_id: str, payload: dict[str, Any]) -> None:
    await _store(comfyui_id, ComfyUIJobRecord(status="completed", payload=payload))


async def register_failure(comfyui_id: str, error: str) -> None:
    await _store(comfyui_id, ComfyUIJobRecord(status="failed", error=error))


async def get_record(comfyui_id: str) -> Optional[ComfyUIJobRecord]:
    try:
        data = await _get_cache().get(_key(comfyui_id))
    except Exception as exc:
        logger.warning("comfyui_registry_redis_unavailable", op="get", error=str(exc))
        data = None
    if data is not None:
        return ComfyUIJobRecord(
            status=data["status"], payload=data.get("payload"), error=data.get("error")
        )
    return _fallback.get(comfyui_id)


async def clear_record(comfyui_id: str) -> None:
    _fallback.pop(comfyui_id, None)
    try:
        await _get_cache().delete(_key(comfyui_id))
    except Exception as exc:
        logger.warning("comfyui_registry_redis_unavailable", op="delete", error=str(exc))
