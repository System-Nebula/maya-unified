"""Machine metadata for PRE-001 baselines (stored separately from results)."""

from __future__ import annotations

import platform
import sys
from typing import Any


def collect_machine_metadata() -> dict[str, Any]:
    """Non-secret host facts — never include transcripts or API keys."""
    meta: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "",
        "system": platform.system(),
        "release": platform.release(),
    }
    try:
        import torch  # type: ignore

        meta["torch"] = getattr(torch, "__version__", "unknown")
        meta["cuda_available"] = bool(torch.cuda.is_available())
        if meta["cuda_available"]:
            meta["cuda_device"] = torch.cuda.get_device_name(0)
    except Exception:  # noqa: BLE001
        meta["torch"] = None
        meta["cuda_available"] = False
    return meta
