"""Maya Unified — internal package paths (single project, no external repos)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PACKAGES_DIR = ROOT / "packages"
VOICE_RUNTIME = PACKAGES_DIR / "voice-runtime"
GATEWAY_SRC = ROOT / "apps" / "maya-gateway" / "src"


def voices_dir() -> Path:
    """Directory for clone reference clips and uploads."""
    return VOICE_RUNTIME / "voices"


def vrm_dir() -> Path:
    """Directory for uploaded VRM avatar models."""
    path = DATA_DIR / "vrm"
    path.mkdir(parents=True, exist_ok=True)
    return path


def vrm_backgrounds_dir() -> Path:
    """Directory for custom VRM scene background images."""
    path = vrm_dir() / "backgrounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def animations_dir() -> Path:
    """Directory for FBX / VRMA idle and gesture clips."""
    path = DATA_DIR / "animations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_voice_ref(path: str) -> str:
    """Resolve settings-relative voice paths to absolute files under voice-runtime."""
    raw = (path or "").strip()
    if not raw:
        return raw
    p = Path(raw)
    if p.is_file():
        return str(p.resolve())
    if p.is_absolute():
        return str(p)
    norm = raw.replace("\\", "/")
    candidates = [
        VOICE_RUNTIME / norm,
        voices_dir() / p.name,
        DATA_DIR / "voices" / p.name,
        ROOT / "examples" / "voices" / p.name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return str((VOICE_RUNTIME / norm).resolve())


def resolve_runtime_file(path: str) -> str:
    """Resolve MCP / VTS config files relative to voice-runtime."""
    raw = (path or "").strip()
    if not raw:
        return raw
    p = Path(raw)
    if p.is_file():
        return str(p.resolve())
    if p.is_absolute():
        return str(p)
    candidate = VOICE_RUNTIME / raw
    return str(candidate.resolve() if candidate.is_file() else candidate)


def agent_data_dir(operator_id: str | None = None) -> Path:
    """Agent memory / DB / personalities — per-operator or legacy global data/."""
    if operator_id:
        path = DATA_DIR / "operators" / str(operator_id)
        path.mkdir(parents=True, exist_ok=True)
        return path
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
