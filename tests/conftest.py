"""Repository-wide pytest bootstrap matching the gateway import layout."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRA_PATHS = (
    ROOT,
    ROOT / "apps" / "discord-shim" / "src",
)
for path in EXTRA_PATHS:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from services.paths import setup_paths  # noqa: E402
setup_paths()
