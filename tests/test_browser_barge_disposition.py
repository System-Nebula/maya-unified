"""Smart browser barge must always terminate duck with resume or clear."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from agent import VoiceAgent
from config import CONFIG
from services.voice.browser_ws import _barge_terminal_payload


class _Playback:
    def __init__(self) -> None:
        self.stop_calls = 0

    def is_playing(self) -> bool:
        return True

    def tts_generating(self) -> bool:
        return True

    def stop(self) -> int:
        self.stop_calls += 1
        return 12


class _STT:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error

    def transcribe_array(self, *_args, **_kwargs) -> str:
        if self.error is not None:
            raise self.error
        return self.text


def _agent(text: str = "", error: Exception | None = None):
    events: list[dict] = []
    queued: list[str] = []
    playback = _Playback()
    agent = SimpleNamespace(
        _session_stop=threading.Event(),
        stt=_STT(text=text, error=error),
        _emit=lambda **event: events.append(event),
        _turn_active=threading.Event(),
        playback=playback,
        barge_mode="smart",
        _pending_user_text=None,
        _barge_in_flag=threading.Event(),
        _enqueue_turn=lambda value: queued.append(value),
    )
    return agent, events, queued, playback


@pytest.fixture(autouse=True)
def _enable_smart_barge(monkeypatch) -> None:
    monkeypatch.setattr(CONFIG.audio, "barge_in", True)


def test_empty_barge_transcript_resumes_ducked_audio() -> None:
    agent, _events, _queued, playback = _agent(text="")
    result = VoiceAgent.submit_browser_utterance(
        agent, np.ones(320, dtype=np.int16), assistant_speaking=True
    )
    assert result == {"outcome": "resume_audio"}
    assert playback.stop_calls == 0
    assert _barge_terminal_payload(result, assistant_speaking=True) == {
        "type": "resume_audio"
    }


def test_filler_barge_transcript_resumes_ducked_audio() -> None:
    agent, _events, _queued, playback = _agent(text="um")
    result = VoiceAgent.submit_browser_utterance(
        agent, np.ones(320, dtype=np.int16), assistant_speaking=True
    )
    assert result == {"outcome": "resume_audio"}
    assert playback.stop_calls == 0


def test_asr_error_resumes_ducked_audio() -> None:
    agent, events, _queued, playback = _agent(error=RuntimeError("asr down"))
    result = VoiceAgent.submit_browser_utterance(
        agent, np.ones(320, dtype=np.int16), assistant_speaking=True
    )
    assert result == {"outcome": "resume_audio"}
    assert playback.stop_calls == 0
    assert any(event.get("type") == "error" for event in events)


def test_meaningful_barge_clears_matching_generation() -> None:
    agent, _events, _queued, playback = _agent(text="please stop talking now")
    result = VoiceAgent.submit_browser_utterance(
        agent, np.ones(320, dtype=np.int16), assistant_speaking=True
    )
    assert result == {"outcome": "clear_audio", "generation_id": 12}
    assert playback.stop_calls == 1
    assert _barge_terminal_payload(result, assistant_speaking=True) == {
        "type": "clear_audio",
        "generation_id": 12,
    }


def test_normal_utterance_queues_without_barge_control() -> None:
    agent, _events, queued, playback = _agent(text="hello maya")
    playback.is_playing = lambda: False
    playback.tts_generating = lambda: False
    result = VoiceAgent.submit_browser_utterance(
        agent, np.ones(320, dtype=np.int16), assistant_speaking=False
    )
    assert result == {"outcome": "queued"}
    assert queued == ["hello maya"]
    assert _barge_terminal_payload(result, assistant_speaking=False) is None
