"""Short prefixed ids for chat message correlation."""

from __future__ import annotations

import uuid

__all__ = ["new_corr_id", "new_message_id", "new_session_id", "new_turn_id"]


def new_corr_id() -> str:
    """Correlate a user prompt with its Maya reply."""
    return f"c_{uuid.uuid4().hex[:12]}"


def new_message_id() -> str:
    """Unique id for one emitted chat message."""
    return f"m_{uuid.uuid4().hex[:12]}"


def new_session_id() -> str:
    """Id for one hands-free voice session."""
    return f"s_{uuid.uuid4().hex[:12]}"


def new_turn_id() -> str:
    """Id for one user→assistant turn within a session."""
    return f"t_{uuid.uuid4().hex[:12]}"
