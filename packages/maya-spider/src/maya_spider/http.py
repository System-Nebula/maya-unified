"""Shared async HTTP helpers — rate limiting and retry policy.

Default path is plain HTTP/JSON. CDP-backed fetch belongs in an optional backend
(not implemented here); callers opt in explicitly when auth or captcha requires it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    retry_attempts: int = 3
    backoff: str = "exponential"


class AsyncRateLimiter:
    """Serialize requests with a minimum interval between acquisitions."""

    def __init__(self, min_interval_s: float) -> None:
        self._min_interval_s = max(0.0, min_interval_s)
        self._lock = asyncio.Lock()
        self._last_acquired = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.perf_counter()
            elapsed = now - self._last_acquired
            remaining = self._min_interval_s - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_acquired = time.perf_counter()


def create_async_client(
    *,
    base_url: str | None = None,
    timeout: float = 15.0,
    follow_redirects: bool = True,
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url or "",
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=headers,
        transport=transport,
    )


async def request_with_retry(
    request_fn: Callable[[], Awaitable[httpx.Response]],
    *,
    failure_policy: FailurePolicy | None = None,
    retry_for: tuple[type[BaseException], ...] = (httpx.RequestError,),
) -> httpx.Response:
    policy = failure_policy or FailurePolicy()
    attempts = max(1, policy.retry_attempts)
    delay = 0.25
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = await request_fn()
            response.raise_for_status()
            return response
        except retry_for as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_STATUS:
                raise
            last_error = exc

        if attempt == attempts:
            break
        await asyncio.sleep(delay)
        if policy.backoff == "exponential":
            delay *= 2

    assert last_error is not None
    raise last_error
