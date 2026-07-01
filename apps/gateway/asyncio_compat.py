"""Suppress harmless Windows Proactor disconnect noise from asyncio."""

from __future__ import annotations

import asyncio
import logging
import sys


class _FilterConnectionReset(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[0] is ConnectionResetError:
            return False
        msg = record.getMessage()
        return "ConnectionResetError" not in msg and "10054" not in msg


def install_logging_filter() -> None:
    if sys.platform != "win32":
        return
    logging.getLogger("asyncio").addFilter(_FilterConnectionReset())


def install_loop_handler() -> None:
    if sys.platform != "win32":
        return
    loop = asyncio.get_running_loop()
    default = loop.get_exception_handler()

    def handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError):
            return
        if default is not None:
            default(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
