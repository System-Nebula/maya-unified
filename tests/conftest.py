"""Repository-wide pytest bootstrap matching gateway and shared fixture imports."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRA_PATHS = (
    ROOT,
    ROOT / "tests",
    ROOT / "apps" / "discord-shim" / "src",
)
for path in EXTRA_PATHS:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from services.paths import setup_paths  # noqa: E402
setup_paths()
