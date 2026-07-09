"""Tests for operator personality reconciliation and active-id resolution."""

from __future__ import annotations

from services.operator_voice.context import resolve_active_personality_id


def test_resolve_prefers_settings_active_id() -> None:
    personalities = {"default": {}, "maya-sama": {}, "gumi": {}}
    assert (
        resolve_active_personality_id(
            personalities,
            file_active="default",
            settings_active_id="maya-sama",
        )
        == "maya-sama"
    )


def test_resolve_falls_back_to_file_active() -> None:
    personalities = {"default": {}, "maya-sama": {}}
    assert (
        resolve_active_personality_id(
            personalities,
            file_active="default",
            settings_active_id="missing",
        )
        == "default"
    )


def test_resolve_picks_first_when_no_match() -> None:
    personalities = {"alpha": {}, "beta": {}}
    assert (
        resolve_active_personality_id(
            personalities,
            file_active="",
            settings_active_id="",
        )
        in personalities
    )


def test_resolve_empty_personalities() -> None:
    assert resolve_active_personality_id({}, settings_active_id="maya-sama") == ""
