"""Tests for shared /play query normalization."""

from __future__ import annotations

from services.cmd.play_query import (
    extract_maya_play_query,
    extract_play_query_from_raw_text,
    looks_like_cmd_residue,
    looks_like_maya_play_request,
    normalize_play_query,
    rewrite_maya_play_as_cmd,
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


def test_extract_maya_play_query_brat_and_nggyu() -> None:
    assert extract_maya_play_query("maya play brat") == "brat"
    assert (
        extract_maya_play_query("maya play never going to give you up")
        == "never going to give you up"
    )
    assert rewrite_maya_play_as_cmd("maya play brat") == "/play brat"
    assert rewrite_maya_play_as_cmd("Maya, play never going to give you up") == (
        "/play never going to give you up"
    )
    assert looks_like_maya_play_request("maya play brat") is True


def test_extract_maya_play_query_wake_variants() -> None:
    assert extract_maya_play_query("@maya play brat") == "brat"
    assert extract_maya_play_query("hey maya play brat") == "brat"
    assert extract_maya_play_query("maya play me brat") == "brat"


def test_extract_maya_play_query_rejects_non_play() -> None:
    assert extract_maya_play_query("hello") is None
    assert extract_maya_play_query("play brat") is None
    assert extract_maya_play_query("/play brat") is None
    assert extract_maya_play_query("maya play pokemon") is None
    assert extract_maya_play_query("maya play next song") is None
    assert extract_maya_play_query("maya pause the music") is None
    assert looks_like_maya_play_request("hello there") is False
