"""Short prefixed ids for chat message correlation."""

from __future__ import annotations

import uuid

__all__ = ["new_corr_id", "new_message_id"]


def new_corr_id() -> str:
    """Correlate a user prompt with its Maya reply."""
    return f"c_{uuid.uuid4().hex[:12]}"


def new_message_id() -> str:
    """Unique id for one emitted chat message."""
    return f"m_{uuid.uuid4().hex[:12]}"
