"""Reference-clip transcript helpers for ICL voice cloning."""

from __future__ import annotations

import os


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
