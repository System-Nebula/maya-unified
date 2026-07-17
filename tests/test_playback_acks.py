"""VOICE-006: browser playback acknowledgments drive StreamPlayer idle."""

from __future__ import annotations

import numpy as np

from player import StreamPlayer


def _tone(samples: int = 240) -> np.ndarray:
    return (np.sin(np.linspace(0, 6.28, samples, dtype=np.float32)) * 0.2).astype(
        np.float32
    )


def test_playback_ended_ack_clears_playing() -> None:
    events: list[dict] = []
    player = StreamPlayer()
    player.set_output_sink("browser")
    player.set_emitter(events.append)

    gen = player.begin_turn(session_id="s1", turn_id="t1", corr_id="c1")
    player.submit(_tone(), 24000, generation_id=gen)
    assert player.is_playing()

    player.note_playback_ack(
        {"type": "playback_ended", "generation_id": gen, "sequence": 1}
    )
    assert not player.is_playing()


def test_stale_playback_ended_ignored_after_new_turn() -> None:
    player = StreamPlayer()
    player.set_output_sink("browser")
    player.set_emitter(lambda _e: None)

    old = player.begin_turn()
    player.submit(_tone(), 24000, generation_id=old)
    player.stop()
    new = player.begin_turn()
    player.submit(_tone(), 24000, generation_id=new)
    assert player.is_playing()

    player.note_playback_ack(
        {"type": "playback_ended", "generation_id": old, "sequence": 1}
    )
    assert player.is_playing()

    player.note_playback_ack(
        {"type": "playback_ended", "generation_id": new, "sequence": 1}
    )
    assert not player.is_playing()


def test_stop_generation_interrupted_ack_cannot_end_new_turn() -> None:
    player = StreamPlayer()
    player.set_output_sink("browser")
    player.set_emitter(lambda _e: None)

    old = player.begin_turn(session_id="s1", turn_id="old")
    player.submit(_tone(), 24000, generation_id=old)
    stop_generation = player.stop()
    new = player.begin_turn(session_id="s1", turn_id="new")
    player.submit(_tone(), 24000, generation_id=new)
    assert player.is_playing()

    accepted = player.note_playback_ack(
        {
            "type": "playback_interrupted",
            "session_id": "s1",
            "turn_id": "old",
            "generation_id": stop_generation,
            "sequence": 1,
        }
    )

    assert accepted is False
    assert player.is_playing(), "a stale stop acknowledgment ended the new turn"


def test_foreign_turn_ack_is_rejected_even_with_current_generation() -> None:
    player = StreamPlayer()
    player.set_output_sink("browser")
    player.set_emitter(lambda _e: None)

    generation = player.begin_turn(session_id="s-current", turn_id="t-current")
    player.submit(_tone(), 24000, generation_id=generation)

    accepted = player.note_playback_ack(
        {
            "type": "playback_ended",
            "session_id": "s-other",
            "turn_id": "t-other",
            "generation_id": generation,
            "sequence": 1,
        }
    )

    assert accepted is False
    assert player.is_playing()


def test_audio_chunks_carry_sequence() -> None:
    events: list[dict] = []
    player = StreamPlayer()
    player.set_output_sink("browser")
    player.set_emitter(events.append)
    gen = player.begin_turn()
    player.submit(_tone(), 24000, generation_id=gen)
    player.submit(_tone(), 24000, generation_id=gen)
    audio = [e for e in events if e.get("type") == "audio"]
    assert [e["sequence"] for e in audio] == [1, 2]
    queued = [e for e in events if e.get("type") == "audio_queued"]
    assert queued[-1]["sequence"] == 2
