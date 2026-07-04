"""Run async coroutines from sync hub/route handlers."""

from __future__ import annotations

import asyncio
import threading
from typing import TypeVar

T = TypeVar("T")

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def schedule_coro(coro) -> None:
    """Fire-and-forget coroutine on the gateway main loop."""
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
        return
    threading.Thread(target=lambda: asyncio.run(coro), daemon=True, name="async-bridge-fallback").start()


def run_sync(coro, *, timeout: float = 120) -> T:
    """Run an async coroutine from sync code without creating a second event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        target = _main_loop or loop
        if target is loop:
            # Blocking this thread would also block the target loop — the coro
            # could never run and we'd sit out the full timeout.
            coro.close()
            raise RuntimeError(
                "run_sync called from the event loop that would execute the "
                "coroutine; wrap the sync call in asyncio.to_thread(...)"
            )
        future = asyncio.run_coroutine_threadsafe(coro, target)
        return future.result(timeout=timeout)

    if _main_loop is not None and _main_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
        return future.result(timeout=timeout)

    return asyncio.run(coro)
