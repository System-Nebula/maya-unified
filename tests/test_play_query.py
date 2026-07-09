"""Tests for shared /play query normalization."""

from __future__ import annotations

from services.cmd.play_query import (
    extract_play_query_from_raw_text,
    looks_like_cmd_residue,
    normalize_play_query,
    salvage_media_url,
)


def test_normalize_play_query_strips_duplicate_prefixes() -> None:
    url = "https://youtu.be/u1NHX9FcHVw?list=RDu1NHX9FcHVw"
    assert normalize_play_query(f"/play {url}") == url
    assert normalize_play_query(f"/play /play {url}") == url
    assert normalize_play_query(f"play play {url}") == url


def test_extract_play_query_from_raw_text() -> None:
    url = "https://www.youtube.com/watch?v=u1NHX9FcHVw"
    assert extract_play_query_from_raw_text(f"/play /play {url}") == url
    assert extract_play_query_from_raw_text("/play daft punk") == "daft punk"
    assert extract_play_query_from_raw_text("/play") == ""


def test_looks_like_cmd_residue() -> None:
    assert looks_like_cmd_residue("/play https://youtu.be/x")
    assert not looks_like_cmd_residue("https://youtu.be/x")
    assert not looks_like_cmd_residue("daft punk")


def test_salvage_media_url_from_cmd_garbage() -> None:
    url = "https://youtu.be/u1NHX9FcHVw"
    assert salvage_media_url(f"/play {url}") == url
