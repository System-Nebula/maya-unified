"""ASR-003: upload limits, queue metrics, off-loop inference helpers."""

from __future__ import annotations

import asyncio
import time

import pytest

from asr_limits import (
    AsrMetrics,
    UploadTooLarge,
    audio_duration_s,
    enforce_duration,
    enforce_upload_size,
)


def test_enforce_upload_size_rejects_oversize() -> None:
    with pytest.raises(UploadTooLarge, match="too large"):
        enforce_upload_size(100, max_bytes=50)


def test_enforce_duration_rejects_long_audio() -> None:
    with pytest.raises(UploadTooLarge, match="too long"):
        enforce_duration(200.0, max_s=120.0)


def test_audio_duration_math() -> None:
    assert audio_duration_s(16000, 16000) == pytest.approx(1.0)
    assert audio_duration_s(0, 16000) == 0.0


def test_metrics_snapshot_includes_queue_fields() -> None:
    m = AsrMetrics(ready=True, model_id="m", waiting=2, in_flight=1, last_inference_ms=12.5)
    snap = m.snapshot()
    assert snap["waiting"] == 2
    assert snap["in_flight"] == 1
    assert snap["queue_depth"] == 3
    assert snap["last_inference_ms"] == 12.5
    assert "max_upload_bytes" in snap


@pytest.mark.asyncio
async def test_semaphore_serializes_jobs() -> None:
    sem = asyncio.Semaphore(1)
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def job() -> None:
        nonlocal active, max_active
        await sem.acquire()
        try:
            async with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1
        finally:
            sem.release()

    await asyncio.gather(job(), job(), job())
    assert max_active == 1


@pytest.mark.asyncio
async def test_to_thread_keeps_event_loop_responsive() -> None:
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    def blocking() -> str:
        time.sleep(0.06)
        return "done"

    tick_task = asyncio.create_task(ticker())
    result = await asyncio.to_thread(blocking)
    await tick_task
    assert result == "done"
    assert ticks >= 3
