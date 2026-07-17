"""AUDIO-001: audio hello negotiation and framed PCM."""

from __future__ import annotations

import pytest

from services.voice.audio_protocol import (
    FRAME_HEADER_SIZE,
    AudioProtocolError,
    FrameStreamState,
    negotiate_audio_hello,
    pack_pcm_frame,
    resample_s16le_mono,
    unpack_pcm_frame,
)


def test_negotiate_accepts_44100_and_48000() -> None:
    for rate in (44100, 48000):
        neg = negotiate_audio_hello(
            {
                "type": "audio_hello",
                "protocol": 1,
                "format": "s16le",
                "sample_rate": rate,
                "channels": 1,
                "frames_per_chunk": 2048,
            }
        )
        assert neg.sample_rate == rate


def test_negotiate_rejects_bad_rate() -> None:
    with pytest.raises(AudioProtocolError):
        negotiate_audio_hello(
            {
                "type": "audio_hello",
                "protocol": 1,
                "format": "s16le",
                "sample_rate": 12345,
                "channels": 1,
                "frames_per_chunk": 2048,
            }
        )


def test_frame_roundtrip_and_gap_detection() -> None:
    pcm = b"\x01\x00" * 64
    framed = pack_pcm_frame(pcm, sequence=0, sample_index=0)
    assert len(framed) == FRAME_HEADER_SIZE + len(pcm)
    state = FrameStreamState()
    out, seq, sample_index, _flags = unpack_pcm_frame(framed, state)
    assert out == pcm and seq == 0 and sample_index == 0

    next_frame = pack_pcm_frame(pcm, sequence=1, sample_index=64)
    unpack_pcm_frame(next_frame, state)

    bad = pack_pcm_frame(pcm, sequence=5, sample_index=200)
    with pytest.raises(AudioProtocolError, match="sequence gap"):
        unpack_pcm_frame(bad, state)
    assert state.gap_count >= 1


def test_resample_44100_to_48000_preserves_duration() -> None:
    # 10 ms at 44.1 kHz
    n = int(44100 * 0.01)
    pcm = (b"\x00\x10" * n)
    out = resample_s16le_mono(pcm, 44100, 48000)
    out_n = len(out) // 2
    assert abs(out_n - int(48000 * 0.01)) <= 2
