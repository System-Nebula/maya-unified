"""Optional fixed arena pair configuration.

By default no fixed pair is set, so battles draw a random opponent from the full pool
of arena-candidate workflows (ZITT, Flux2, Ideogram4, Krea2). Set
``MAYA_ARENA_PAIR="wf_a,wf_b"`` to force a specific head-to-head instead.
"""

from __future__ import annotations

import os


def arena_pair_from_env() -> tuple[str, str] | None:
    """Return (workflow_a, workflow_b) from MAYA_ARENA_PAIR, or None for the random pool."""
    raw = os.getenv("MAYA_ARENA_PAIR", "off").strip()
    if not raw or raw.lower() in {"0", "false", "off", "no"}:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 2:
        return parts[0], parts[1]
    return None
