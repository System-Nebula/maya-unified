"""Bounded queue helpers with explicit overflow policy (VOICE-004)."""

from __future__ import annotations

import asyncio
import queue
from typing import TypeVar

T = TypeVar("T")


def put_keep_newest(q: queue.Queue, item: T) -> bool:
    """Put `item`, dropping the oldest entry if the queue is full.

    Returns True if at least one older item was discarded.
    """
    dropped = False
    while True:
        try:
            q.put_nowait(item)
            return dropped
        except queue.Full:
            try:
                q.get_nowait()
                dropped = True
                try:
                    q.task_done()
                except ValueError:
                    pass
            except queue.Empty:
                # Raced with a consumer; retry put.
                continue


def drain_queue(q: queue.Queue) -> int:
    """Remove all pending items. Returns how many were discarded."""
    n = 0
    while True:
        try:
            q.get_nowait()
            n += 1
            try:
                q.task_done()
            except ValueError:
                pass
        except queue.Empty:
            return n


async def async_put_keep_newest(q: asyncio.Queue, item: T) -> bool:
    """Asyncio variant of put_keep_newest."""
    dropped = False
    while True:
        try:
            q.put_nowait(item)
            return dropped
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                dropped = True
                try:
                    q.task_done()
                except ValueError:
                    pass
            except asyncio.QueueEmpty:
                continue
