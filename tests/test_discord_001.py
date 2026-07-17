"""DISCORD-001: hybrid part=, emit kwargs, smart barge duck."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_VOICE_RUNTIME = _ROOT / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_discord_vc_sentence_wav_part_is_keyword_only() -> None:
    from agent import VoiceAgent

    sig = inspect.signature(VoiceAgent._discord_vc_sentence_wav)
    part = sig.parameters["part"]
    assert part.kind is inspect.Parameter.KEYWORD_ONLY


def test_hybrid_fn_must_use_part_kwarg() -> None:
    """Mirror DiscordManager hybrid call sites: part= is required."""

    def hybrid(text, instruct, *, part: str):
        return f"{part}:{text}"

    assert hybrid("hi", None, part="first") == "first:hi"
    with pytest.raises(TypeError):
        hybrid("hi", None, "first")  # type: ignore[misc]


def test_emit_accepts_kwargs_and_legacy_dict() -> None:
    from agent import VoiceAgent

    events: list[dict] = []

    agent = object.__new__(VoiceAgent)
    agent.on_event = events.append
    agent._turn_corr_id = None
    agent._session_id = "s1"
    agent._turn_ctx = None
    agent._event_seq = 0
    agent._next_event_sequence = lambda: 1  # type: ignore[method-assign]

    with patch("agent.stamp_event", side_effect=lambda e, **_k: e):
        agent._emit(type="user", text="hello")
        agent._emit({"type": "assistant", "text": "hi"})

    assert events[0]["type"] == "user"
    assert events[0]["text"] == "hello"
    assert events[1]["type"] == "assistant"
    assert events[1]["text"] == "hi"


def _manager_with_fake_voice(*, volume: float = 1.0):
    import discord

    from tools.discord_bot import DiscordManager

    mgr = DiscordManager(token="test-token")
    src = MagicMock(spec=discord.PCMVolumeTransformer)
    src.volume = volume
    voice = SimpleNamespace(
        is_connected=lambda: True,
        is_playing=lambda: True,
        is_paused=lambda: False,
        source=src,
        stop=MagicMock(),
    )
    mgr._voice = voice
    mgr._vc_speaking = True
    mgr._now_playing = None
    mgr._sync_active_voice = lambda: voice  # type: ignore[method-assign]
    mgr._force_stop_playback = MagicMock()  # type: ignore[method-assign]
    return mgr, voice, src


def test_smart_barge_onset_ducks_without_stop() -> None:
    mgr, voice, src = _manager_with_fake_voice(volume=1.0)
    with patch.object(mgr, "_vc_barge_mode", return_value="smart"):
        asyncio.run(mgr._vc_barge_onset_async(7, 12.0))
    assert mgr._vc_ducked is True
    assert src.volume < 1.0
    mgr._force_stop_playback.assert_not_called()
    assert mgr._vc_speaking is True


def test_instant_barge_onset_stops() -> None:
    mgr, voice, src = _manager_with_fake_voice(volume=1.0)
    with patch.object(mgr, "_vc_barge_mode", return_value="instant"):
        asyncio.run(mgr._vc_barge_onset_async(7, 12.0))
    assert mgr._vc_speaking is False
    mgr._force_stop_playback.assert_called_once_with(voice)
    assert mgr._vc_ducked is False


def test_unduck_restores_volume() -> None:
    mgr, _voice, src = _manager_with_fake_voice(volume=1.0)
    assert mgr._duck_vc_reply(0.1) is True
    assert abs(src.volume - 0.1) < 1e-6
    mgr._unduck_vc_reply()
    assert abs(src.volume - 1.0) < 1e-6
    assert mgr._vc_ducked is False


def test_off_barge_onset_noop() -> None:
    mgr, _voice, src = _manager_with_fake_voice(volume=1.0)
    with patch.object(mgr, "_vc_barge_mode", return_value="off"):
        asyncio.run(mgr._vc_barge_onset_async(7, 12.0))
    assert src.volume == 1.0
    assert mgr._vc_ducked is False
    mgr._force_stop_playback.assert_not_called()
