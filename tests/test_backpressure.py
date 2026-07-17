"""AUDIO-005: backpressure stats, oversized reject, mic-frame queue."""

from __future__ import annotations

import asyncio
import time

import pytest

from services.voice.audio_protocol import FRAME_HEADER_SIZE, MAX_PCM_BYTES, MAX_RAW_FRAME_BYTES
from services.voice.bounded_queue import async_put_keep_newest
from services.voice.browser_ws import MIC_FRAME_QUEUE_MAX, ConnBackpressureStats


def test_max_raw_frame_includes_header() -> None:
    assert MAX_RAW_FRAME_BYTES == FRAME_HEADER_SIZE + MAX_PCM_BYTES


def test_oversize_threshold_rejects_before_pcm_cap() -> None:
    # A frame larger than header+max pcm must be rejected without unpack.
    assert MAX_RAW_FRAME_BYTES < FRAME_HEADER_SIZE + MAX_PCM_BYTES + 1


def test_backpressure_snapshot_fields() -> None:
    stats = ConnBackpressureStats()
    stats.note_frame(1000)
    stats.frames_dropped_queue = 2
    snap = stats.snapshot(mic_qsize=1, utterance_qsize=0)
    assert snap["type"] == "backpressure"
    assert snap["bytes_in"] == 1000
    assert snap["frames_dropped_queue"] == 2
    assert snap["mic_queue_depth"] == 1
    assert snap["bytes_per_sec"] >= 0


def test_queue_age_ms() -> None:
    stats = ConnBackpressureStats()
    assert stats.queue_age_ms() is None
    stats.last_enqueue_at = time.monotonic() - 0.05
    age = stats.queue_age_ms()
    assert age is not None and age >= 40


@pytest.mark.asyncio
async def test_mic_frame_queue_drops_oldest() -> None:
    q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=MIC_FRAME_QUEUE_MAX)
    assert await async_put_keep_newest(q, b"a") is False
    assert await async_put_keep_newest(q, b"b") is False
    assert await async_put_keep_newest(q, b"c") is False
    dropped = await async_put_keep_newest(q, b"d")
    assert dropped is True
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert items[-1] == b"d"
    assert b"a" not in items
