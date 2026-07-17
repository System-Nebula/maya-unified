"""VOICE-004: receive path must not await ASR; overflow stays bounded."""

from __future__ import annotations

import asyncio
import time

import pytest

from services.voice.bounded_queue import async_put_keep_newest


@pytest.mark.asyncio
async def test_receive_path_stays_responsive_while_asr_queued() -> None:
    """Enqueuing finalized utterances must return quickly even if ASR is slow."""
    q: asyncio.Queue[tuple[bytes, bool] | None] = asyncio.Queue(maxsize=2)
    processed: list[bytes] = []
    started = asyncio.Event()

    async def slow_asr_worker() -> None:
        while True:
            item = await q.get()
            if item is None:
                q.task_done()
                return
            started.set()
            await asyncio.sleep(0.2)
            processed.append(item[0])
            q.task_done()

    worker = asyncio.create_task(slow_asr_worker())
    t0 = time.perf_counter()
    # Simulate receive loop: enqueue without awaiting ASR.
    assert await async_put_keep_newest(q, (b"one", False)) is False
    assert await async_put_keep_newest(q, (b"two", False)) is False
    dropped = await async_put_keep_newest(q, (b"three", False))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert dropped is True
    assert elapsed_ms < 50, f"enqueue blocked for {elapsed_ms:.1f}ms"

    await q.put(None)
    await worker
    # Oldest dropped; worker should see two then three (order after drop).
    assert processed[-1] == b"three"
    assert b"one" not in processed or processed[0] != b"one" or len(processed) <= 2
