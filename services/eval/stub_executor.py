"""Re-export ToolExecutor — stub behavior lives in registry_fixtures handlers."""

from __future__ import annotations

import sys
from pathlib import Path

_VOICE_RUNTIME = Path(__file__).resolve().parents[2] / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))

from tools.executor import ToolExecutor  # noqa: E402

__all__ = ["ToolExecutor"]
