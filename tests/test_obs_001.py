"""OBS-001: voice latency / queue metrics (IDs and numbers only)."""

from __future__ import annotations

import pytest

from services.voice.metrics import (
    VOICE_COUNTERS,
    VOICE_EVENTS,
    VOICE_HISTOGRAMS,
    assert_no_content_keys,
    get_voice_metrics,
    known_metric_names,
    new_turn_timeline,
    record_stale_generation_drop,
)
from services.voice.session_controller import VoiceSessionController
from services.voice.audience import Audience


@pytest.fixture(autouse=True)
def _reset_metrics():
    get_voice_metrics().reset()
    yield
    get_voice_metrics().reset()


def test_plan_metric_names_are_registered() -> None:
    names = set(known_metric_names())
    for expected in (
        "voice.endpoint.ms",
        "voice.asr.ms",
        "voice.llm.ttft_ms",
        "voice.tts.ttfa_ms",
        "voice.e2e.first_audio_ms",
        "voice.frames.dropped",
        "voice.ws.reconnects",
        "voice.queue.depth",
        "voice.audio.underruns",
        "voice.generation.stale_drops",
    ):
        assert expected in names


def test_timeline_flush_records_durations_without_content() -> None:
    tl = new_turn_timeline(session_id="s1", turn_id="t1", generation_id=3)
    t0 = 100.0
    tl.mark("speech_end", at=t0)
    tl.mark("endpoint_finalized", at=t0 + 0.05)
    tl.mark("asr_queued", at=t0 + 0.05)
    tl.mark("asr_start", at=t0 + 0.06)
    tl.mark("asr_end", at=t0 + 0.20)
    tl.mark("llm_request", at=t0 + 0.21)
    tl.mark("llm_first_token", at=t0 + 0.31)
    tl.mark("tts_start", at=t0 + 0.40)
    tl.mark("tts_first_pcm", at=t0 + 0.45)
    tl.mark("first_audio_sent", at=t0 + 0.46)

    recorded = tl.flush_durations(get_voice_metrics())
    assert recorded["voice.endpoint.ms"] == pytest.approx(50.0)
    assert recorded["voice.asr.ms"] == pytest.approx(140.0)
    assert recorded["voice.llm.ttft_ms"] == pytest.approx(100.0)
    assert recorded["voice.tts.ttfa_ms"] == pytest.approx(50.0)
    assert recorded["voice.e2e.first_audio_ms"] == pytest.approx(460.0)

    snap = get_voice_metrics().snapshot()
    assert_no_content_keys(snap)
    assert_no_content_keys(tl.to_public_dict())
    assert "transcript" not in tl.to_public_dict()
    assert snap["histograms"]["voice.asr.ms"] == [pytest.approx(140.0)]


def test_forbidden_meta_is_stripped() -> None:
    get_voice_metrics().observe(
        "voice.asr.ms",
        12.0,
        meta={
            "transcript": "hello secret",
            "prompt": "system",
            "generation_id": 9,
            "token": "sk-leak",
        },
    )
    snap = get_voice_metrics().snapshot()
    assert snap["last_meta"] == {"generation_id": 9}
    assert_no_content_keys(snap)


def test_unknown_event_rejected() -> None:
    tl = new_turn_timeline()
    with pytest.raises(ValueError):
        tl.mark("not_a_real_event")


def test_stale_complete_start_increments_counter() -> None:
    ctl = VoiceSessionController()
    started = ctl.begin_start(Audience.operator("op-a"))
    assert started["ok"]
    out = ctl.complete_start(started["session_id"], started["generation_id"] + 99, ok=True)
    assert out["error"] == "stale"
    assert get_voice_metrics().snapshot()["counters"]["voice.generation.stale_drops"] == 1


def test_event_catalog_covers_plan_markers() -> None:
    for name in (
        "speech_start",
        "speech_end",
        "endpoint_finalized",
        "llm_first_token",
        "tts_first_pcm",
        "first_audio_played_ack",
        "barge_onset",
        "barge_duck",
    ):
        assert name in VOICE_EVENTS
    assert "voice.barge.duck_ms" in VOICE_HISTOGRAMS
    assert "voice.sse.dropped" in VOICE_COUNTERS
