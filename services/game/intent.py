"""Detect video-game play requests vs music/Discord play commands."""

from __future__ import annotations

import re
from typing import Optional

_GAME_KEYWORDS = (
    "pokemon",
    "pokémon",
    "pokmon",
    "fire red",
    "firered",
    "fire-red",
    "emerald",
    "ruby",
    "sapphire",
    "leaf green",
    "mgba",
    "emulator",
    "game boy",
    "gameboy",
    "gba",
    "nintendo",
    "zelda",
    "mario",
    "video game",
    "videogame",
    "starter pokemon",
    "gym leader",
    "professor oak",
    "viridian",
    "pallet town",
    "beat the game",
    "end of the game",
    "finish the game",
    "complete the game",
    "play through",
    "speedrun",
    "game mode",
    "game bridge",
)

_MUSIC_HINTS = (
    "youtube",
    "spotify",
    "song",
    "track",
    "album",
    "playlist",
    "bandcamp",
    "artist",
    "on discord",
    "in discord",
    "voice channel",
)


def _has_game_keyword(tl: str) -> bool:
    return any(k in tl for k in _GAME_KEYWORDS)


def is_game_play_request(user_text: str) -> bool:
    """True when the user wants Maya to play a video game (not music)."""
    tl = (user_text or "").lower().strip()
    if not tl:
        return False
    if not _has_game_keyword(tl):
        # "play until we beat it" without naming pokemon — still game if no music hints
        if re.search(r"\bplay\b.+\buntil\b", tl) and not any(h in tl for h in _MUSIC_HINTS):
            if any(w in tl for w in ("beat", "win", "finish", "complete", "end of")):
                return True
        return False
    if any(h in tl for h in _MUSIC_HINTS) and not re.search(
        r"\b(pokemon|pokémon|mgba|emulator|gba|nintendo)\b", tl
    ):
        return False
    return True


def extract_game_goal(user_text: str) -> Optional[str]:
    """Pull an autonomous goal from natural language."""
    original = (user_text or "").strip()
    tl = original.lower()
    if not is_game_play_request(original):
        return None

    m = re.search(r"\buntil\s+(.+?)(?:[.!?]|$)", original, re.I)
    if m:
        goal = m.group(1).strip(" .,!?'\"")
        if len(goal) >= 3:
            return goal

    if "end of the game" in tl:
        return "reach the end of the game"
    if any(p in tl for p in ("beat the game", "finish the game", "complete the game")):
        return "beat the game"
    if "professor oak" in tl or "intro" in tl:
        return "get through Professor Oak intro"
    if "starter" in tl:
        return "choose starter Pokemon"

    # Default for open-ended play requests
    if _has_game_keyword(tl):
        return "beat the game"
    return None


def extract_game_profile(user_text: str) -> str:
    tl = (user_text or "").lower()
    if any(k in tl for k in ("pokemon", "pokémon", "fire red", "firered", "gba", "mgba")):
        return "pokemon_gba"
    return "pokemon_gba"
