"""Tests for game narration filtering + chat emit."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.narration import prepare_game_say  # noqa: E402


def test_prepare_game_say_drops_button_read():
    assert prepare_game_say("Pressing A to advance.") == ""
    assert prepare_game_say("Mashing B here.") == ""


def test_prepare_game_say_keeps_streamer_lines():
    assert "Oak" in prepare_game_say("Professor Oak won't stop talking, classic.")
    assert "Eevee" in prepare_game_say("Wait is that an Eevee on the screen??")


def test_prepare_game_say_strips_voice_cue():
    assert prepare_game_say("VOICE: bored, dismissive, sighing") == ""
    assert prepare_game_say("VOICE: warm\nGary is so extra.") == "Gary is so extra."


def test_prepare_game_say_empty():
    assert prepare_game_say("") == ""
    assert prepare_game_say("   ") == ""
