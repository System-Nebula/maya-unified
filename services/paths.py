"""Resolve bundled qwen3-voice-agent + maya-public inside this repo."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def _first_existing(*candidates: Path) -> Path:
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


# Bundled in-repo (canonical). Sibling layout kept as a dev fallback only.
VOICE_AGENT = _first_existing(
    ROOT / "qwen3-voice-agent",
    ROOT.parent / "qwen3-voice-agent",
)
MAYA_PUBLIC = _first_existing(
    ROOT / "maya-public",
    ROOT.parent / "maya-public",
)


def agent_data_dir() -> Path:
    """Agent memory / DB / personalities — always maya-unified/data."""
    return DATA_DIR


def setup_paths() -> None:
    """Insert qwen3-voice-agent and maya-public packages ahead of imports."""
    candidates: list[Path] = []
    if VOICE_AGENT.is_dir():
        candidates.append(VOICE_AGENT)
    if MAYA_PUBLIC.is_dir():
        gw = MAYA_PUBLIC / "apps" / "maya-gateway" / "src"
        if gw.is_dir():
            candidates.append(gw)
        packages = MAYA_PUBLIC / "packages"
        if packages.is_dir():
            for pkg in sorted(packages.iterdir()):
                src = pkg / "src"
                if src.is_dir():
                    candidates.append(src)
    for path in candidates:
        s = str(path.resolve())
        if s not in sys.path:
            sys.path.insert(0, s)
