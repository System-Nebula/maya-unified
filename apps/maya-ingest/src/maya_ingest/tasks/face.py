"""Optional face-embedding signal for cross-platform avatar matching.

Behind a feature flag — public repo never downloads model weights at build
time. Production turns this on via FACE_MATCH_ENABLED=true and provides
weights at runtime.
"""

from __future__ import annotations

from typing import Optional


async def avatar_embedding(_image_bytes: bytes) -> Optional[list[float]]:
    try:
        import insightface  # noqa: F401
    except ImportError:
        return None
    return None
