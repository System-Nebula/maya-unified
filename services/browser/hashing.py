"""Content hash for capture idempotency."""

from __future__ import annotations

import hashlib

from maya_contracts import CaptureEvent


def compute_content_hash(event: CaptureEvent) -> str:
    """Hash url + reader_text/selection so re-clipping the same page is idempotent."""
    basis = "|".join(
        [
            event.url,
            event.reader_text or "",
            event.selection or "",
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
