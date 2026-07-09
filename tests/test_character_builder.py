"""Tests for LLM character card builder fallbacks."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
_VOICE_RUNTIME = _ROOT / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))

from memory.character_builder import (  # noqa: E402
    _fallback_card_from_brief,
    build_character_from_prompt,
)


class _EmptyLLM:
    def complete(self, messages, **kwargs):  # noqa: ANN001, ARG002
        return SimpleNamespace(content="", reasoning_content="")


class _JsonLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def complete(self, messages, **kwargs):  # noqa: ANN001, ARG002
        return SimpleNamespace(content=self.payload, reasoning_content="")


def test_fallback_card_from_gumi_bio() -> None:
    brief = """So hi im Gumi

I like to play games my favorite game is Bloodborne.

I guess you can say im a variety streamer?

Sif is best doggo :3"""
    card = _fallback_card_from_brief(brief)
    assert card["name"] == "Gumi"
    assert "Bloodborne" in card["description"]
    assert "streamer" in card["tags"]
    assert "gaming" in card["tags"]


def test_build_uses_fallback_when_llm_empty() -> None:
    brief = "So hi im Gumi. I like Bloodborne."
    card = build_character_from_prompt(_EmptyLLM(), brief)
    assert card["name"] == "Gumi"
    assert card["personality"]


def test_build_parses_json_llm_response() -> None:
    payload = (
        '{"name":"Gumi","description":"streamer","personality":"playful",'
        '"scenario":"live stream","first_mes":"hey","mes_example":"<START>",'
        '"post_history_instructions":"stay in character","tags":["gaming"]}'
    )
    card = build_character_from_prompt(_JsonLLM(payload), "ignored brief")
    assert card["name"] == "Gumi"
    assert card["tags"] == ["gaming"]


if __name__ == "__main__":
    test_fallback_card_from_gumi_bio()
    test_build_uses_fallback_when_llm_empty()
    test_build_parses_json_llm_response()
    print("ok")
