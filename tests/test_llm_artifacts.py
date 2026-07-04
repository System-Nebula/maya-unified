"""Strip pseudo tool calls and roleplay control tokens from spoken text."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
sys.path.insert(0, str(ROOT))

from agent import finalize_reply_text  # noqa: E402
from memory.character_card import (  # noqa: E402
    extract_pseudo_tool_calls,
    polish_spoken_reply,
    strip_llm_artifacts,
)


def test_strip_pseudo_expression_and_start():
    raw = (
        "set_avatar_expression(mood='excited') <START> Maya: "
        "\"Hey, what's up everyone! Try to keep up, alright?\""
    )
    assert strip_llm_artifacts(raw).startswith("Maya:")
    reply, _ = finalize_reply_text(raw)
    assert reply == "Hey, what's up everyone! Try to keep up, alright?"


def test_strip_pseudo_animation_keeps_dialogue():
    raw = (
        "play_avatar_animation(clip_name='do_a_flip') "
        "I'm doing a flip to say hello! Try not to get dizzy watching me."
    )
    reply, _ = finalize_reply_text(raw)
    assert reply == (
        "I'm doing a flip to say hello! Try not to get dizzy watching me."
    )


def test_extract_pseudo_tool_calls():
    raw = (
        "set_avatar_expression(mood='happy') "
        "play_avatar_animation(clip_name='wave') Hi!"
    )
    calls = extract_pseudo_tool_calls(raw)
    assert ("set_avatar_expression", {"mood": "happy"}) in calls
    assert ("play_avatar_animation", {"clip_name": "wave"}) in calls
    assert polish_spoken_reply(raw) == "Hi!"
