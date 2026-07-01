"""Maya Unified — internal package paths (single project, no external repos)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PACKAGES_DIR = ROOT / "packages"
VOICE_RUNTIME = PACKAGES_DIR / "voice-runtime"
GATEWAY_SRC = ROOT / "apps" / "maya-gateway" / "src"


def agent_data_dir() -> Path:
    """Agent memory / DB / personalities — repo-root data/."""
    return DATA_DIR


def setup_paths() -> None:
    """Insert voice runtime + platform packages on sys.path before imports."""
    candidates: list[Path] = []
    if VOICE_RUNTIME.is_dir():
        candidates.append(VOICE_RUNTIME)
    if GATEWAY_SRC.is_dir():
        candidates.append(GATEWAY_SRC)
    if PACKAGES_DIR.is_dir():
        for pkg in sorted(PACKAGES_DIR.iterdir()):
            if pkg.name == "voice-runtime":
                continue
            src = pkg / "src"
            if src.is_dir():
                candidates.append(src)
    for path in candidates:
        s = str(path.resolve())
        if s not in sys.path:
            sys.path.insert(0, s)
