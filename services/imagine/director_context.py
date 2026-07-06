"""Per-request context for image director agent tools."""

from __future__ import annotations

import contextvars
from typing import Any

_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "image_director_ctx",
    default={},
)


def set_image_director_context(**kwargs: Any) -> None:
    current = dict(_ctx.get({}))
    current.update({k: v for k, v in kwargs.items() if v is not None})
    _ctx.set(current)


def get_image_director_context() -> dict[str, Any]:
    return dict(_ctx.get({}))
