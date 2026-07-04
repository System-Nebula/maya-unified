"""Tests for VOICE: delivery cue stripping."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
sys.path.insert(0, str(ROOT))

from agent import extract_voice_cues_from_text, finalize_reply_text  # noqa: E402


def test_strip_embedded_voice_line():
    raw = (
        "Heyyy, everyone! Just here to kick some ass and make some noise!\n\n"
        "VOICE: sarcastic, dry, smirk\n"
        "Who's ready for a little chaos? Let's go!"
    )
    body, cue = extract_voice_cues_from_text(raw)
    assert cue == "sarcastic, dry, smirk"
    assert "VOICE:" not in body
    assert "Who's ready" in body
    assert "kick some ass" in body


def test_strip_inline_voice_cue():
    raw = (
        "Heyyy, everyone! Just here to kick some ass and make some noise! "
        "VOICE: sarcastic, dry, smirk Who's ready for a little chaos? Let's go!"
    )
    body, cue = extract_voice_cues_from_text(raw)
    assert cue == "sarcastic, dry, smirk"
    assert body == (
        "Heyyy, everyone! Just here to kick some ass and make some noise! "
        "Who's ready for a little chaos? Let's go!"
    )


def test_finalize_reply_text_strips_emoji_and_voice():
    raw = "VOICE: warm\nHello 😀 world"
    reply, cue = finalize_reply_text(raw)
    assert cue == "warm"
    assert reply == "Hello world"


def test_collapse_immediate_duplicate():
    from memory.character_card import collapse_immediate_duplicate, polish_spoken_reply

    dup = "Maya: Hey, what's up!" * 2
    assert collapse_immediate_duplicate(dup) == "Maya: Hey, what's up!"
    reply, _ = finalize_reply_text(dup)
    assert reply == "Hey, what's up!"


def test_strip_dialogue_name_prefix():
    from memory.character_card import polish_spoken_reply

    assert polish_spoken_reply("Maya: Hey, what's up!") == "Hey, what's up!"
    assert polish_spoken_reply("Maya-sama: Premium content only.") == "Premium content only."

    from memory.character_card import peel_leading_delivery_asterisk, strip_roleplay_actions

    raw = "*whispers* Don't tell anyone I said this."
    peeled, cue = peel_leading_delivery_asterisk(raw)
    assert cue == "whispers"
    assert strip_roleplay_actions(peeled) == "Don't tell anyone I said this."
    reply, delivery = finalize_reply_text(raw)
    assert delivery == "whispers"
    assert reply == "Don't tell anyone I said this."


def test_strip_action_keeps_dialogue_after():
    raw = "*flips through the air, landing with a soft thud on one foot* Heyyy, everyone!"
    reply, _ = finalize_reply_text(raw)
    assert reply == "Heyyy, everyone!"
    assert "*" not in reply


def test_salvage_dialogue_wrapped_in_asterisks():
    from memory.character_card import strip_roleplay_actions

    raw = "*Hey everyone, who's ready for a little chaos?*"
    assert strip_roleplay_actions(raw) == "Hey everyone, who's ready for a little chaos?"
