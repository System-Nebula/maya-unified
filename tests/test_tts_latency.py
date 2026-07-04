"""Tests for TTS latency instrumentation, cache keys, and streaming frames."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.voice import tts_cache
from services.voice.tts_stream import TtsStreamEncoder, timing_response_headers


def test_cache_key_includes_mode_and_model() -> None:
    a = tts_cache.cache_key("hi", "", "ref.wav", "clone", "Qwen/Qwen3-TTS-0.6B")
    b = tts_cache.cache_key("hi", "", "ref.wav", "custom", "Qwen/Qwen3-TTS-1.7B")
    assert a != b
    assert len(a) == 64


def test_active_model_id_respects_mode() -> None:
    assert tts_cache.active_model_id("clone", "m-clone", "m-custom") == "m-clone"
    assert tts_cache.active_model_id("custom", "m-clone", "m-custom") == "m-custom"


def test_timing_response_headers() -> None:
    headers = timing_response_headers(
        {"ttfa_ms": 412.7, "synth_ms": 2800, "encode_ms": 9, "total_ms": 2850, "lock_wait_ms": 0},
        cache="miss",
        cache_key="abc",
    )
    assert headers["X-TTS-TTFA-Ms"] == "413"
    assert headers["X-TTS-Synth-Ms"] == "2800"
    assert headers["X-TTS-Cache"] == "miss"
    assert "X-TTS-TTFA-Ms" in headers["Access-Control-Expose-Headers"]


def test_tts_stream_encoder_yields_meta_pcm_done() -> None:
    pcm = np.array([0.1, -0.1, 0.2], dtype=np.float32).tobytes()

    def _chunks():
        yield pcm, 24000, True, {"prefill_ms": 300, "decode_ms": 120, "lock_wait_ms": 2}
        yield pcm, 24000, False, {"decode_ms": 80}

    enc = TtsStreamEncoder(cache_key="deadbeef")
    frames = list(enc.frames(_chunks()))
    assert len(frames) >= 3
    meta_len = struct.unpack("<I", frames[0][:4])[0]
    meta = json.loads(frames[0][4 : 4 + meta_len].decode("utf-8"))
    assert meta["sr"] == 24000
    assert meta["hash"] == "deadbeef"
    assert enc.wav_bytes is not None
    assert enc.wav_bytes[:4] == b"RIFF"
    assert enc.timing["ttfa_ms"] >= 0


def test_iter_speech_yields_incrementally() -> None:
    sys.path.insert(0, str(ROOT / "packages" / "voice-runtime"))
    from services.paths import setup_paths

    setup_paths()

    from agent import VoiceAgent  # noqa: E402

    chunks = [
        (np.array([0.0, 0.1], dtype=np.float32), 24000, {"prefill_ms": 1, "decode_ms": 2}),
        (np.array([0.2, 0.3], dtype=np.float32), 24000, {"decode_ms": 2}),
    ]

    class _FakeVoice:
        available = True

        def stream_timed(self, text, stop=None, instruct=None):
            yield from chunks

    agent = SimpleNamespace(
        voice=_FakeVoice(),
        _ensure_icl_ref_text=lambda: None,
        _resolve_render_instruct=lambda instruct: instruct,
    )

    out = list(VoiceAgent.iter_speech(agent, "hello"))
    assert len(out) == 2
    assert out[0][2] is True
    assert out[1][2] is False


def test_hub_render_speech_merges_lock_wait_timing() -> None:
    from services.voice import hub as hub_mod

    mock_agent = MagicMock()
    mock_agent.voice = MagicMock()
    mock_agent.voice.available = True
    mock_agent.render_speech.return_value = (
        b"RIFFxxxx",
        24000,
        {"ttfa_ms": 100, "synth_ms": 200, "encode_ms": 5, "total_ms": 210},
    )

    voice_hub = hub_mod.VoiceHub()
    voice_hub.ready = True
    voice_hub.agent = mock_agent

    wav, sr, timing = voice_hub.render_speech("hello")
    assert wav == b"RIFFxxxx"
    assert sr == 24000
    assert "lock_wait_ms" in timing
    assert timing["ttfa_ms"] == 100


def test_render_speech_returns_timing_dict() -> None:
    sys.path.insert(0, str(ROOT / "packages" / "voice-runtime"))
    from services.paths import setup_paths

    setup_paths()

    from agent import VoiceAgent  # noqa: E402

    pcm = np.linspace(-0.2, 0.2, 480, dtype=np.float32)

    class _FakeVoice:
        available = True

        def stream_timed(self, text, stop=None, instruct=None):
            yield pcm, 24000, {"prefill_ms": 100, "decode_ms": 50}

    agent = SimpleNamespace(
        voice=_FakeVoice(),
        _ensure_icl_ref_text=lambda: None,
        _resolve_render_instruct=lambda instruct: instruct,
    )

    wav_bytes, sr, timing = VoiceAgent.render_speech(agent, "hello")
    assert sr == 24000
    assert wav_bytes[:4] == b"RIFF"
    assert timing["ttfa_ms"] >= 0
    assert timing["synth_ms"] >= 0
    assert timing["engine_prefill_ms"] == 100
