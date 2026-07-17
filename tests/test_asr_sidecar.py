"""ASR sidecar autostart helpers."""

from __future__ import annotations

from services.voice.asr_sidecar import asr_autostart_enabled, resolve_asr_bind


def test_resolve_asr_rewrites_vts_port() -> None:
    host, port, model, base = resolve_asr_bind(
        {"dictation": {"asr_base_url": "http://127.0.0.1:8001/v1", "asr_model": "Qwen/X"}}
    )
    assert port == 8091
    assert "8091" in base
    assert model == "Qwen/X"
    assert host == "127.0.0.1"


def test_autostart_follows_backend() -> None:
    assert asr_autostart_enabled({"dictation": {"backend": "qwen3-asr"}}) is True
    assert asr_autostart_enabled({"dictation": {"backend": "whisper"}}) is False
