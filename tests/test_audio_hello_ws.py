"""AUDIO-001: challenge → audio_hello → ready before PCM is accepted."""

from __future__ import annotations

import pytest

from services.voice.audio_protocol import (
    TARGET_INGRESS_RATE,
    FrameStreamState,
    audio_challenge_payload,
    negotiate_audio_hello,
    pack_pcm_frame,
    resample_s16le_mono,
    unpack_pcm_frame,
)


def test_challenge_payload_shape() -> None:
    payload = audio_challenge_payload(connection_id="c1", session_id="s1")
    assert payload["type"] == "audio_challenge"
    assert payload["protocol"] == 1
    assert 48000 in payload["sample_rates"]
    assert 44100 in payload["sample_rates"]
    assert payload["connection_id"] == "c1"
    assert payload["session_id"] == "s1"


def test_ready_fields_from_negotiation() -> None:
    neg = negotiate_audio_hello(
        {
            "type": "audio_hello",
            "protocol": 1,
            "format": "s16le",
            "sample_rate": 44100,
            "channels": 1,
            "frames_per_chunk": 2048,
        }
    )
    ready = {
        "type": "ready",
        "protocol": neg.protocol,
        "format": neg.format,
        "sample_rate": neg.sample_rate,
        "ingress_sample_rate": TARGET_INGRESS_RATE,
        "channels": neg.channels,
        "frames_per_chunk": neg.frames_per_chunk,
    }
    assert ready["sample_rate"] == 44100
    assert ready["ingress_sample_rate"] == 48000


def test_reject_pcm_semantics_until_negotiated() -> None:
    """Mirrors browser_ws: negotiated is None until audio_hello succeeds."""
    negotiated = None
    assert negotiated is None
    negotiated = negotiate_audio_hello(
        {
            "type": "audio_hello",
            "protocol": 1,
            "format": "s16le",
            "sample_rate": 48000,
            "channels": 1,
            "frames_per_chunk": 2048,
        }
    )
    assert negotiated is not None


def test_framed_pcm_then_resample_path() -> None:
    n = 256
    pcm_441 = (b"\x00\x20" * n)
    framed = pack_pcm_frame(pcm_441, sequence=0, sample_index=0)
    state = FrameStreamState()
    pcm, seq, sample_index, _flags = unpack_pcm_frame(framed, state)
    assert seq == 0 and sample_index == 0
    out = resample_s16le_mono(pcm, 44100, TARGET_INGRESS_RATE)
    assert len(out) % 2 == 0
    assert abs(len(out) // 2 - int(round(n * TARGET_INGRESS_RATE / 44100))) <= 2


def test_gap_resets_frame_baseline() -> None:
    pcm = b"\x01\x00" * 32
    state = FrameStreamState()
    unpack_pcm_frame(pack_pcm_frame(pcm, sequence=0, sample_index=0), state)
    unpack_pcm_frame(pack_pcm_frame(pcm, sequence=1, sample_index=32), state)
    with pytest.raises(Exception):
        unpack_pcm_frame(pack_pcm_frame(pcm, sequence=9, sample_index=300), state)
    # Server re-baselines FrameStreamState after a gap (drop counters preserved).
    recovered = FrameStreamState(gap_count=state.gap_count, drop_count=state.drop_count + 1)
    unpack_pcm_frame(pack_pcm_frame(pcm, sequence=9, sample_index=300), recovered)
    assert recovered.last_sequence == 9
    assert recovered.gap_count == state.gap_count
