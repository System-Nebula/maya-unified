"""Regression tests for the browser duplex audio ingress."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from services.voice import duplex_ingress


def _pcm16(value: int, samples: int = 480) -> bytes:
    return np.full(samples, value, dtype="<i2").tobytes()


def _vad(**kwargs):
    base = dict(
        rms_threshold=0.01,
        silence_ms=100,
        min_speech_ms=0,
        max_turn_ms=30000,
        start_hysteresis_ms=0,
        preroll_ms=0,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _passthrough(data: bytes, *, user_id: int = 0, enhancer_key=None) -> bytes:
    return data


def test_streamed_utterance_is_not_enhanced_twice(monkeypatch) -> None:
    pcm48 = _pcm16(1200)
    expected = np.array([7, 8, 9], dtype=np.int16)
    downsample_calls: list[bytes] = []

    def fake_downsample(data: bytes) -> np.ndarray:
        downsample_calls.append(data)
        return expected

    monkeypatch.setattr(
        "services.voice.hushmic.downsample_mono_48k_to_16k_int16",
        fake_downsample,
    )
    monkeypatch.setattr(
        duplex_ingress,
        "enhance_pcm48_mono",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("streamed audio must not be enhanced a second time")
        ),
    )

    actual = duplex_ingress.utterance_pcm48_to_int16_16k(pcm48)

    assert downsample_calls == [pcm48]
    np.testing.assert_array_equal(actual, expected)


def test_each_browser_chunk_has_one_stream_processing_pass(monkeypatch) -> None:
    monkeypatch.setattr(duplex_ingress, "_vad_config", lambda: _vad())
    calls: list[bytes] = []

    def process_once(data: bytes, *, user_id: int = 0, enhancer_key=None) -> bytes:
        assert user_id == 17
        calls.append(data)
        return data

    monkeypatch.setattr(duplex_ingress, "process_stream_chunk", process_once)
    session = duplex_ingress.DuplexIngressSession()
    # 10 ms voiced + 100 ms silence at 48 kHz
    voiced = _pcm16(3000, samples=480)
    silent = _pcm16(0, samples=4800)

    signal, finalized = duplex_ingress.ingest_pcm_chunk(session, voiced, user_id=17)
    assert signal is duplex_ingress.ChunkSignal.NONE
    assert finalized is None

    signal, finalized = duplex_ingress.ingest_pcm_chunk(session, silent, user_id=17)
    assert signal is duplex_ingress.ChunkSignal.FINALIZE
    assert finalized == voiced + silent
    assert calls == [voiced, silent]


def test_empty_streamed_utterance_skips_downsampler(monkeypatch) -> None:
    downsample = lambda _data: (_ for _ in ()).throw(AssertionError("not expected"))
    monkeypatch.setattr(
        "services.voice.hushmic.downsample_mono_48k_to_16k_int16", downsample
    )

    actual = duplex_ingress.utterance_pcm48_to_int16_16k(b"")

    assert actual.dtype == np.int16
    assert actual.size == 0


def test_backlogged_processing_matches_realtime_endpoint(monkeypatch) -> None:
    """Wall-clock compression must not change silence/max-turn decisions."""
    monkeypatch.setattr(duplex_ingress, "_vad_config", lambda: _vad(silence_ms=50))
    monkeypatch.setattr(
        duplex_ingress, "process_stream_chunk", _passthrough
    )

    voiced = _pcm16(4000, samples=960)  # 20 ms
    silent_frame = _pcm16(0, samples=480)  # 10 ms
    # 50 ms silence = 5 frames

    def run() -> bytes | None:
        session = duplex_ingress.DuplexIngressSession()
        duplex_ingress.ingest_pcm_chunk(session, voiced)
        finalized = None
        for _ in range(5):
            signal, pcm = duplex_ingress.ingest_pcm_chunk(session, silent_frame)
            if signal is duplex_ingress.ChunkSignal.FINALIZE:
                finalized = pcm
                break
        return finalized

    a = run()
    b = run()
    assert a is not None and a == b
    assert a.startswith(voiced)


def test_max_turn_caps_unbounded_noise(monkeypatch) -> None:
    monkeypatch.setattr(
        duplex_ingress,
        "_vad_config",
        lambda: _vad(silence_ms=10_000, max_turn_ms=100, min_speech_ms=0),
    )
    monkeypatch.setattr(
        duplex_ingress, "process_stream_chunk", _passthrough
    )
    session = duplex_ingress.DuplexIngressSession()
    # Continuous voiced noise; 100 ms max at 48 kHz = 4800 samples.
    chunk = _pcm16(5000, samples=960)  # 20 ms
    finalized = None
    for _ in range(10):
        signal, pcm = duplex_ingress.ingest_pcm_chunk(session, chunk)
        if signal is duplex_ingress.ChunkSignal.FINALIZE:
            finalized = pcm
            break
    assert finalized is not None
    duration_ms = duplex_ingress.samples_to_ms(len(finalized) // 2)
    assert duration_ms >= 100
    assert duration_ms < 250  # finalized on the chunk that crossed the cap


def test_barge_off_ignores_speech_while_assistant_speaking(monkeypatch) -> None:
    monkeypatch.setattr(duplex_ingress, "_vad_config", lambda: _vad())
    monkeypatch.setattr(
        duplex_ingress, "process_stream_chunk", _passthrough
    )
    session = duplex_ingress.DuplexIngressSession()
    session.set_assistant_speaking(True)
    signal, _ = duplex_ingress.ingest_pcm_chunk(
        session, _pcm16(8000, samples=4800), barge_mode="off"
    )
    assert signal is duplex_ingress.ChunkSignal.NONE
    assert session.speech_start_sample is None
    assert len(session.recording) == 0


def test_barge_instant_interrupts_on_sustained_voice(monkeypatch) -> None:
    monkeypatch.setattr(duplex_ingress, "_vad_config", lambda: _vad())
    monkeypatch.setattr(
        duplex_ingress, "process_stream_chunk", _passthrough
    )
    session = duplex_ingress.DuplexIngressSession()
    session.set_assistant_speaking(True)
    # 180 ms sustained at 48 kHz
    chunk = _pcm16(8000, samples=8640)
    signal, _ = duplex_ingress.ingest_pcm_chunk(
        session, chunk, barge_mode="instant", barge_onset_ms=180
    )
    assert signal is duplex_ingress.ChunkSignal.INTERRUPT


def test_barge_smart_ducks_on_sustained_voice(monkeypatch) -> None:
    monkeypatch.setattr(duplex_ingress, "_vad_config", lambda: _vad())
    monkeypatch.setattr(
        duplex_ingress, "process_stream_chunk", _passthrough
    )
    session = duplex_ingress.DuplexIngressSession()
    session.set_assistant_speaking(True)
    chunk = _pcm16(8000, samples=8640)
    signal, _ = duplex_ingress.ingest_pcm_chunk(
        session, chunk, barge_mode="smart", barge_onset_ms=180
    )
    assert signal is duplex_ingress.ChunkSignal.DUCK


def test_sustained_barge_resets_across_silence(monkeypatch) -> None:
    monkeypatch.setattr(duplex_ingress, "_vad_config", lambda: _vad(start_hysteresis_ms=0))
    monkeypatch.setattr(
        duplex_ingress, "process_stream_chunk", _passthrough
    )
    session = duplex_ingress.DuplexIngressSession()
    session.set_assistant_speaking(True)
    short = _pcm16(8000, samples=2400)  # 50 ms < 180
    duplex_ingress.ingest_pcm_chunk(session, short, barge_mode="smart", barge_onset_ms=180)
    duplex_ingress.ingest_pcm_chunk(
        session, _pcm16(0, samples=480), barge_mode="smart", barge_onset_ms=180
    )
    assert session.sustained_voice_samples == 0
    signal, _ = duplex_ingress.ingest_pcm_chunk(
        session, short, barge_mode="smart", barge_onset_ms=180
    )
    assert signal is duplex_ingress.ChunkSignal.NONE  # need another 180 ms sustained


def test_preroll_prepended_on_speech_start(monkeypatch) -> None:
    monkeypatch.setattr(
        duplex_ingress,
        "_vad_config",
        lambda: _vad(silence_ms=50, preroll_ms=20, start_hysteresis_ms=0),
    )
    monkeypatch.setattr(
        duplex_ingress, "process_stream_chunk", _passthrough
    )
    session = duplex_ingress.DuplexIngressSession()
    quiet = _pcm16(0, samples=960)  # 20 ms preroll
    voiced = _pcm16(4000, samples=960)
    silent = _pcm16(0, samples=2400)  # 50 ms
    duplex_ingress.ingest_pcm_chunk(session, quiet)
    duplex_ingress.ingest_pcm_chunk(session, voiced)
    signal, pcm = duplex_ingress.ingest_pcm_chunk(session, silent)
    assert signal is duplex_ingress.ChunkSignal.FINALIZE
    assert pcm is not None
    assert pcm.startswith(quiet)
    assert voiced in pcm
