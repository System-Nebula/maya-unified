"""Run async coroutines from sync hub/route handlers."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="async-bridge")


def run_sync(coro) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    future = _executor.submit(asyncio.run, coro)
    return future.result(timeout=120)
