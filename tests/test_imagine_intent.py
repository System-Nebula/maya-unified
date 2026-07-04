"""Tests for natural-language imagine intent detection."""

from __future__ import annotations

from services.imagine.intent import (
    extract_imagine_prompt,
    looks_like_imagine_request,
    parse_imagine_model_from_text,
)


def test_looks_like_imagine_request_draw_object() -> None:
    assert looks_like_imagine_request("draw a stupid dog wearing a party hat") is True


def test_looks_like_imagine_request_generate_image() -> None:
    assert looks_like_imagine_request("generate an image of a sunset") is True


def test_looks_like_imagine_request_plain_chat() -> None:
    assert looks_like_imagine_request("what is the weather today") is False
    assert looks_like_imagine_request("tell me a joke") is False


def test_extract_imagine_prompt_strips_draw_verb() -> None:
    prompt = extract_imagine_prompt("draw a stupid dog wearing a party hat")
    assert prompt == "stupid dog wearing a party hat"


def test_extract_imagine_prompt_generate_image_of() -> None:
    prompt = extract_imagine_prompt("generate an image of a mountain lake")
    assert "mountain lake" in prompt


def test_parse_imagine_model_from_text() -> None:
    assert parse_imagine_model_from_text("draw krea2 sunset") == "krea2"
    assert parse_imagine_model_from_text("draw with zit") == "zit"
    assert parse_imagine_model_from_text("draw a cat") is None
