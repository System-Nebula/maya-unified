"""DISCORD-002: generation-aware VC reply + short sink locks."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_VOICE_RUNTIME = _ROOT / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_begin_vc_reply_bumps_generation_and_cancels_task() -> None:
    from tools.discord_bot import DiscordManager

    mgr = DiscordManager(token="test-token")
    mgr._vc_reply_gen = 3
    mgr._vc_is_reply_playing = lambda: False  # type: ignore[method-assign]

    async def _slow() -> None:
        await asyncio.sleep(60)

    async def _run() -> None:
        task = asyncio.create_task(_slow())
        mgr._vc_reply_task = task
        gen = mgr._begin_vc_reply()
        assert gen == 4
        assert mgr._vc_reply_gen == 4
        await asyncio.sleep(0)
        assert task.cancelled() or task.done()

    asyncio.run(_run())


def test_compose_superseded_when_gen_advances() -> None:
    from tools.discord_bot import DiscordManager

    mgr = DiscordManager(token="test-token")
    mgr._vc_is_reply_playing = lambda: False  # type: ignore[method-assign]
    mgr._voice_hybrid_fn = MagicMock(return_value=b"RIFF")
    played: list[int] = []

    async def _fake_play(wav: bytes, *, generation: int | None = None) -> bool:
        played.append(int(generation or -1))
        return True

    mgr._play_wav_bytes = _fake_play  # type: ignore[method-assign]

    events: list[str] = []

    def on_utterance(_ctx):
        events.append("compose")
        # Simulate barge during compose (generation advanced after begin).
        mgr._vc_reply_gen += 1
        return "Hello there friend."

    mgr._on_vc_utterance = on_utterance
    mgr._transcribe_fn = lambda _pcm, _sr: "please stop talking now"
    mgr._voice_listen_enabled = lambda: True  # type: ignore[method-assign]

    async def _run() -> None:
        await mgr._process_vc_utterance(
            {
                "author_id": 1,
                "author": "a",
                "pcm_mono_16k": np.zeros(3200, dtype=np.int16),
                "sample_rate": 16000,
                "peak_energy": 500.0,
                "duration_sec": 0.5,
            }
        )
        await asyncio.sleep(0.05)

    with patch("tools.discord_bot._vc_should_accept_transcript", return_value=True), patch(
        "tools.discord_bot._vc_meaningful_transcript", return_value=True
    ):
        asyncio.run(_run())

    assert events == ["compose"]
    assert played == []


def test_spawn_replaces_prior_reply_task() -> None:
    from tools.discord_bot import DiscordManager

    mgr = DiscordManager(token="test-token")

    async def _run() -> None:
        first = mgr._spawn_vc_reply_task(asyncio.sleep(60), name="first")
        second = mgr._spawn_vc_reply_task(asyncio.sleep(0.01), name="second")
        await asyncio.sleep(0)
        assert first.cancelled() or first.done()
        await second
        assert mgr._vc_reply_task is None or mgr._vc_reply_task.done()

    asyncio.run(_run())


def test_flush_does_not_hold_lock_during_hushmic() -> None:
    from tools.discord_vc_listen import _UserBuf, build_utterance_sink

    held_during_dsp = {"value": True}

    sink = build_utterance_sink(on_utterance=lambda _p: None)
    real_lock = sink._lock

    def wrapped_hush(pcm_stereo: bytes, user_id: int = 0):
        held_during_dsp["value"] = real_lock.locked()
        return np.zeros(3200, dtype=np.int16)

    stereo = (np.ones(48000 * 2, dtype=np.int16) * 2000).tobytes()
    sink._bufs[9] = _UserBuf(
        chunks=[stereo],
        last_write_at=time.monotonic() - 5,
        started_at=time.monotonic() - 5,
        bytes_total=len(stereo),
        peak_energy=2000.0,
    )
    with patch(
        "services.voice.duplex_ingress.discord_stereo_utterance_to_int16_16k",
        side_effect=wrapped_hush,
    ):
        item = sink._take_user_locked(9, reason="silence")
        assert item is not None
        assert not real_lock.locked()
        sink._process_taken_utterance(*item)

    assert held_during_dsp["value"] is False
    assert 9 in sink._pending
    sink.cleanup()
