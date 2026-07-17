"""PERF-001: first-sentence LLM/TTS overlap and no full-reply buffer."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_VOICE_RUNTIME = _ROOT / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# >= VA_CHUNK_MIN_CHARS (24) so sentence_chunks flushes before more tokens.
_FIRST = "Hello there my friend, how are you today."
_REST = "And then the story continues onward."


def _agent_stub():
    from agent import VoiceAgent

    agent = object.__new__(VoiceAgent)
    agent._barge_in_flag = threading.Event()
    agent._turn_instruct = None
    agent.playback = SimpleNamespace(generation_id=7)
    agent._emit_events: list[dict] = []
    agent._speak_calls: list[str] = []
    agent._order: list[str] = []

    def _emit(**event):
        agent._emit_events.append(event)

    def _speak(text: str, *, xvec_only=None):
        agent._order.append(f"speak:{text}")
        agent._speak_calls.append(text)
        time.sleep(0.02)

    agent._emit = _emit  # type: ignore[method-assign]
    agent._emit_tts_info = lambda: None  # type: ignore[method-assign]
    agent._speak = _speak  # type: ignore[method-assign]
    return agent


def test_hybrid_speaks_first_before_llm_finishes_sync() -> None:
    """Without overlap: still speak at first sentence boundary (not after full LLM)."""
    from config import CONFIG

    agent = _agent_stub()

    def tokens():
        yield f"{_FIRST} "
        agent._order.append("llm_continued")
        yield _REST

    with patch.object(CONFIG.tts, "llm_overlap", False):
        reply = agent._deliver(
            "hybrid",
            tokens(),
            corr_id="c1",
            reply_message_id="m1",
        )

    assert _FIRST in reply
    speak_idx = next(i for i, x in enumerate(agent._order) if x.startswith("speak:"))
    cont_idx = agent._order.index("llm_continued")
    assert speak_idx < cont_idx


def test_hybrid_overlap_tts_runs_concurrent_with_llm() -> None:
    from config import CONFIG

    agent = _agent_stub()
    first_speaking = threading.Event()
    llm_continued = threading.Event()

    def _speak(text: str, *, xvec_only=None):
        agent._speak_calls.append(text)
        agent._order.append(f"speak:{text}")
        if text.startswith("Hello"):
            first_speaking.set()
            assert llm_continued.wait(2.0), "LLM should continue while first TTS runs"
            time.sleep(0.02)

    agent._speak = _speak  # type: ignore[method-assign]

    def tokens():
        yield f"{_FIRST} "
        assert first_speaking.wait(2.0), "first TTS should start before more tokens"
        llm_continued.set()
        agent._order.append("llm_continued")
        yield _REST

    with patch.object(CONFIG.tts, "llm_overlap", True):
        reply = agent._deliver(
            "hybrid",
            tokens(),
            corr_id="c1",
            reply_message_id="m1",
        )

    assert _FIRST in reply
    assert any(s.startswith("Hello") for s in agent._speak_calls)
    assert any("continues" in s for s in agent._speak_calls)
    assert "llm_continued" in agent._order


def test_stale_generation_skips_tts_worker_item() -> None:
    from config import CONFIG

    agent = _agent_stub()
    agent.playback = SimpleNamespace(generation_id=1)

    def tokens():
        yield f"{_FIRST} "
        agent.playback.generation_id = 2  # barge / new turn
        yield "Should not speak this remainder as live."

    with patch.object(CONFIG.tts, "llm_overlap", True):
        agent._deliver(
            "hybrid",
            tokens(),
            corr_id="c1",
            reply_message_id="m1",
        )

    assert not any("remainder" in s for s in agent._speak_calls)
