"""VOICE-002 slice: captured generation IDs prevent stale browser audio."""

from __future__ import annotations

import numpy as np

from player import StreamPlayer


def _tone(samples: int = 240) -> np.ndarray:
    return (np.sin(np.linspace(0, 6.28, samples, dtype=np.float32)) * 0.2).astype(
        np.float32
    )


def test_begin_turn_stamps_audio_events_with_captured_generation() -> None:
    from services.voice.audience import Audience

    events: list[dict] = []
    player = StreamPlayer()
    player.set_output_sink("browser")
    player.set_emitter(events.append)

    gen = player.begin_turn(
        session_id="s_test",
        turn_id="t_test",
        corr_id="c_test",
        audience=Audience.operator("op_9"),
    )
    player.submit(_tone(), 24000, generation_id=gen)

    assert events[0]["type"] == "audio_begin"
    assert events[0]["generation_id"] == gen
    assert events[0]["session_id"] == "s_test"
    assert events[0]["turn_id"] == "t_test"
    assert events[0]["corr_id"] == "c_test"
    assert events[0]["audience"] == {"kind": "operator", "id": "op_9"}
    audio = next(ev for ev in events if ev["type"] == "audio")
    assert audio["generation_id"] == gen
    assert audio["session_id"] == "s_test"
    assert audio["turn_id"] == "t_test"
    assert audio["audience"] == {"kind": "operator", "id": "op_9"}
    assert audio["format"] == "f32le"


def test_stale_submit_after_generation_advance_is_dropped() -> None:
    events: list[dict] = []
    player = StreamPlayer()
    player.set_output_sink("browser")
    player.set_emitter(events.append)

    old_gen = player.begin_turn()
    player.stop()
    new_gen = player.begin_turn()
    assert new_gen != old_gen

    before = len(events)
    player.submit(_tone(), 24000, generation_id=old_gen)
    assert all(ev.get("type") != "audio" for ev in events[before:])

    player.submit(_tone(), 24000, generation_id=new_gen)
    audio = [ev for ev in events[before:] if ev.get("type") == "audio"]
    assert len(audio) == 1
    assert audio[0]["generation_id"] == new_gen


def test_stop_advances_generation_so_late_audio_stop_is_stale() -> None:
    events: list[dict] = []
    player = StreamPlayer()
    player.set_output_sink("browser")
    player.set_emitter(events.append)

    playing_gen = player.begin_turn()
    player.submit(_tone(), 24000, generation_id=playing_gen)

    stop_gen = player.stop()
    assert stop_gen != playing_gen
    stop_events = [ev for ev in events if ev["type"] == "audio_stop"]
    assert stop_events[-1]["generation_id"] == stop_gen

    next_gen = player.begin_turn()
    assert next_gen != stop_gen
    assert next_gen != playing_gen
    # A delayed stop for the prior turn must not share the new turn's id.
    assert playing_gen != next_gen
