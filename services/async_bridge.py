"""Run async coroutines from sync hub/route handlers."""

from __future__ import annotations

import asyncio
from typing import TypeVar

T = TypeVar("T")

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def run_sync(coro) -> T:
    """Run an async coroutine from sync code without creating a second event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        target = _main_loop or loop
        future = asyncio.run_coroutine_threadsafe(coro, target)
        return future.result(timeout=120)

    if _main_loop is not None and _main_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, _main_loop)
        return future.result(timeout=120)

    return asyncio.run(coro)
