"""VOICE-004: bounded queue overflow policy."""

from __future__ import annotations

import asyncio
import queue

import pytest

from services.voice.bounded_queue import async_put_keep_newest, drain_queue, put_keep_newest


def test_put_keep_newest_drops_oldest() -> None:
    q: queue.Queue[str] = queue.Queue(maxsize=2)
    assert put_keep_newest(q, "a") is False
    assert put_keep_newest(q, "b") is False
    assert put_keep_newest(q, "c") is True
    assert q.get_nowait() == "b"
    assert q.get_nowait() == "c"
    assert q.empty()


def test_drain_queue_clears_pending() -> None:
    q: queue.Queue[int] = queue.Queue(maxsize=4)
    put_keep_newest(q, 1)
    put_keep_newest(q, 2)
    assert drain_queue(q) == 2
    assert q.empty()
    assert drain_queue(q) == 0


@pytest.mark.asyncio
async def test_async_put_keep_newest_drops_oldest() -> None:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
    assert await async_put_keep_newest(q, "a") is False
    assert await async_put_keep_newest(q, "b") is False
    assert await async_put_keep_newest(q, "c") is True
    assert q.get_nowait() == "b"
    assert q.get_nowait() == "c"
