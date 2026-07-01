"""Tests for maya-spider HTTP helpers."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from maya_spider.http import AsyncRateLimiter, request_with_retry


@pytest.mark.asyncio
async def test_rate_limiter_serializes() -> None:
    limiter = AsyncRateLimiter(0.05)
    t0 = asyncio.get_event_loop().time()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - t0
    assert elapsed >= 0.04


@pytest.mark.asyncio
async def test_request_with_retry_on_transient_error() -> None:
    calls = 0

    async def flaky() -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, request=httpx.Request("GET", "http://test"))

    resp = await request_with_retry(flaky)
    assert resp.status_code == 200
    assert calls == 2
