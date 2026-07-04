"""Content-addressed TTS audio cache on local disk."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from services.paths import DATA_DIR

_SEP = "\x1f"
_CACHE_DIR = DATA_DIR / "tts_cache"

__all__ = ["cache_key", "get", "put", "active_model_id"]


def active_model_id(mode: str, clone_model: str, custom_model: str) -> str:
    """Return the HuggingFace model id used for the active TTS mode."""
    return (clone_model if (mode or "").lower() == "clone" else custom_model) or ""


def cache_key(
    text: str,
    instruct: str,
    voice_id: str,
    mode: str,
    model_id: str,
    *,
    xvec_only: bool | None = None,
) -> str:
    """sha256 hex key from text + instruct + voice + mode + model + xvec flag."""
    xvec = "" if xvec_only is None else ("1" if xvec_only else "0")
    payload = _SEP.join(
        [
            (text or "").strip(),
            (instruct or "").strip(),
            (voice_id or "").strip(),
            (mode or "").strip().lower(),
            (model_id or "").strip(),
            xvec,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _path(key: str) -> Path:
    if not key or len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
        raise ValueError("invalid cache key")
    return _CACHE_DIR / f"{key}.wav"


def get(key: str) -> bytes | None:
    try:
        path = _path(key)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def put(key: str, wav_bytes: bytes) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _path(key)
    fd, tmp = tempfile.mkstemp(dir=_CACHE_DIR, suffix=".wav.tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(wav_bytes)
        os.replace(tmp, dest)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
