"""Tests for dashboard music queue intent and player append."""

from __future__ import annotations

from services.dashboard.music_intent import (
    extract_dashboard_queue_query,
    looks_like_dashboard_queue_request,
    queue_after_current,
)
from services.dashboard.player import (
    _player_cache,
    build_playlist_artifact,
    clear_player_state,
    remember_player_append,
    remember_player_load,
)


def test_extract_play_next() -> None:
    assert extract_dashboard_queue_query("play gagnam style next") == "gagnam style"
    assert queue_after_current("play gagnam style next") is True


def test_extract_add_to_queue() -> None:
    assert extract_dashboard_queue_query("add hyuna bubble pop to the queue") == "hyuna bubble pop"
    assert extract_dashboard_queue_query("add lofi to queue") == "lofi"
    assert queue_after_current("add hyuna bubble pop to the queue") is False


def test_extract_queue_next_colon() -> None:
    assert extract_dashboard_queue_query("queue next: lofi hip hop") == "lofi hip hop"
    assert queue_after_current("queue next: lofi hip hop") is True


def test_extract_queue_prefix() -> None:
    assert extract_dashboard_queue_query("queue lofi hip hop") == "lofi hip hop"
    assert looks_like_dashboard_queue_request("queue lofi hip hop") is True


def test_remember_player_append_after_current() -> None:
    clear_player_state(operator_id="op-test")
    _player_cache.pop("op-test", None)
    first = build_playlist_artifact("despacito", None)
    remember_player_load(first, operator_id="op-test")
    second = build_playlist_artifact("gangnam style", None)
    merged = remember_player_append(second, operator_id="op-test", after_current=True)
    tracks = merged.get("tracks") or []
    assert len(tracks) == 2
    assert "despacito" in tracks[0]["query"].lower()
    assert "gangnam" in tracks[1]["query"].lower()
    clear_player_state(operator_id="op-test")


def test_remember_player_append_tail() -> None:
    clear_player_state(operator_id="op-tail")
    first = build_playlist_artifact("track a", None)
    remember_player_load(first, operator_id="op-tail")
    second = build_playlist_artifact("track b", None)
    merged = remember_player_append(second, operator_id="op-tail", after_current=False)
    tracks = merged.get("tracks") or []
    assert len(tracks) == 2
    assert tracks[1]["query"] == "track b"
    clear_player_state(operator_id="op-tail")
