"""Shared fal.ai AsyncClient utilities for submit/poll across providers."""

from __future__ import annotations

import asyncio
import os
from typing import Any


class FalHandleCache:
    """Maps request_id → AsyncRequestHandle for reuse across poll calls."""

    def __init__(self) -> None:
        self._handles: dict[str, Any] = {}

    def store(self, request_id: str, handle: Any) -> None:
        self._handles[request_id] = handle

    def get_or_create(self, client: Any, endpoint_id: str, request_id: str) -> Any:
        if request_id not in self._handles:
            try:
                from fal_client import AsyncRequestHandle
            except ImportError as exc:
                raise RuntimeError("fal-client is required") from exc
            handle = AsyncRequestHandle.from_request_id(
                client, endpoint_id, request_id
            )
            self._handles[request_id] = handle
        return self._handles[request_id]

    def remove(self, request_id: str) -> None:
        self._handles.pop(request_id, None)


def get_fal_client(api_key: str | None = None) -> Any:
    """Return an AsyncClient using FAL_KEY env var by default."""
    try:
        from fal_client import AsyncClient
    except ImportError as exc:
        raise RuntimeError("fal-client is required: uv add fal-client") from exc
    return AsyncClient(key=api_key or os.getenv("FAL_KEY"))


async def fal_submit(client: Any, endpoint_id: str, payload: dict) -> tuple[str, Any]:
    """Submit a job to a fal endpoint. Returns (request_id, handle)."""
    handle = await client.submit(endpoint_id, arguments=payload)
    return handle.request_id, handle


async def fal_poll(
    client: Any,
    endpoint_id: str,
    request_id: str,
    cache: FalHandleCache,
    max_attempts: int = 60,
    base_delay: float = 3.0,
) -> tuple[str, dict | None, str | None]:
    """
    Poll a fal job with retry and exponential backoff.

    Returns:
        (status, result_or_none, error_or_none)
    """
    handle = cache.get_or_create(client, endpoint_id, request_id)

    for attempt in range(max_attempts):
        try:
            result = await handle.get()
            cache.remove(request_id)
            return "completed", result, None
        except Exception as e:
            error_str = str(e).lower()
            if "in progress" in error_str or "not ready" in error_str:
                delay = base_delay * (1.5**min(attempt, 8))
                await asyncio.sleep(delay)
                continue
            cache.remove(request_id)
            return "error", None, str(e)

    cache.remove(request_id)
    return "timeout", None, f"Polling timed out after {max_attempts} attempts"
