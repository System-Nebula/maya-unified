"""Tests for degraded/stub TTS when the model or package is unavailable."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

VOICE_RUNTIME = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))

from config import TTSConfig  # noqa: E402
from tts import NullTTS, load_tts  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_tts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VA_TTS_ENABLED", raising=False)


def test_load_tts_disabled_returns_null(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VA_TTS_ENABLED", "0")
    cfg = TTSConfig()
    voice = load_tts(cfg)
    assert isinstance(voice, NullTTS)
    assert voice.available is False
    assert list(voice.stream("hello")) == []


def test_null_tts_set_reference_raises() -> None:
    voice = NullTTS(TTSConfig(), reason="test")
    with pytest.raises(RuntimeError, match="TTS unavailable"):
        voice.set_reference("missing.wav")


def test_load_tts_import_failure_falls_back() -> None:
    cfg = TTSConfig(enabled=True, mode="custom")
    with patch("tts.Qwen3TTS", side_effect=ImportError("no faster_qwen3_tts")):
        voice = load_tts(cfg)

    assert isinstance(voice, NullTTS)
    assert voice.available is False
    assert "no faster_qwen3_tts" in voice.degrade_reason


def test_load_tts_model_load_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = TTSConfig(enabled=True, mode="custom")

    class _FakeQwen:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("CUDA out of memory")

    with patch("tts.Qwen3TTS", _FakeQwen):
        voice = load_tts(cfg)

    assert isinstance(voice, NullTTS)
    assert "CUDA out of memory" in voice.degrade_reason
