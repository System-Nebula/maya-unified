"""Tests for game vs music intent routing."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.intent import (  # noqa: E402
    extract_game_goal,
    is_game_play_request,
)


def test_pokemon_play_is_game_not_music():
    text = "play Pokemon until we get to the end of the game"
    assert is_game_play_request(text)
    assert extract_game_goal(text) == "we get to the end of the game"


def test_discord_music_is_not_game():
    text = "play never gonna give you up on discord"
    assert not is_game_play_request(text)


def test_end_of_game_goal():
    text = "Hey, can you play Pokemon until you reach the end of the game?"
    assert is_game_play_request(text)
    assert extract_game_goal(text) == "you reach the end of the game"
