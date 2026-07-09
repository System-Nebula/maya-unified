"""Reference-clip transcript helpers for ICL voice cloning."""

from __future__ import annotations

import logging
import os
from typing import Callable


def read_ref_text_sidecar(ref_audio: str) -> str:
    """Read `<clip>.txt` or `ref.txt` beside the reference wav, if present."""
    if not ref_audio:
        return ""
    base, _ = os.path.splitext(ref_audio)
    ref_dir = os.path.dirname(ref_audio) or "."
    for candidate in (f"{base}.txt", os.path.join(ref_dir, "ref.txt")):
        if os.path.exists(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    return fh.read().strip()
            except OSError:
                pass
    return ""


def ensure_ref_text_sidecar(
    path: str,
    *,
    stt=None,
    transcribe: Callable[[str], str] | None = None,
    log: logging.Logger | None = None,
) -> str:
    """Return transcript for clip `path`, reading or creating `<stem>.txt`."""
    if not path or not os.path.isfile(path):
        return ""
    sidecar = os.path.splitext(path)[0] + ".txt"
    if os.path.exists(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as fh:
                text = fh.read().strip()
            if text:
                return text
        except OSError:
            pass

    _log = log or logging.getLogger("voice-agent.ref_text")
    if transcribe is not None:
        try:
            text = (transcribe(path) or "").strip()
        except Exception as exc:  # noqa: BLE001
            _log.warning("reference transcription failed: %s", exc)
            return ""
    else:
        if stt is None:
            try:
                from stt import create_stt

                stt = create_stt()
            except Exception as exc:  # noqa: BLE001
                _log.warning("reference STT unavailable: %s", exc)
                return ""
        _log.info("transcribing reference for ICL: %s", os.path.basename(path))
        try:
            text = (stt.transcribe_file(path) or "").strip()
        except Exception as exc:  # noqa: BLE001
            _log.warning("reference transcription failed: %s", exc)
            return ""

    if text:
        try:
            with open(sidecar, "w", encoding="utf-8") as fh:
                fh.write(text)
            _log.info("saved transcript -> %s", os.path.basename(sidecar))
        except OSError:
            pass
    return text


def sync_clone_ref_text(tts_cfg, *, explicit: str | None = None) -> None:
    """Align `tts_cfg.ref_text` with `tts_cfg.ref_audio`.

    Non-empty `explicit` wins. Otherwise load the sidecar for the current clip.
    If neither exists, leave empty so the agent can Whisper-transcribe on first speak.
    """
    if explicit:
        tts_cfg.ref_text = explicit.strip()
        return
    tts_cfg.ref_text = ""
    if not (tts_cfg.ref_audio or "").strip():
        return
    sidecar = read_ref_text_sidecar(tts_cfg.ref_audio)
    if sidecar:
        tts_cfg.ref_text = sidecar


def clear_voice_prompt_cache(tts_model) -> None:
    """Drop cached ICL/xvec prompts after reference or transcript changes."""
    cache = getattr(tts_model, "_voice_prompt_cache", None)
    if isinstance(cache, dict):
        cache.clear()
