"""Tests for music string normalization (paths, remix tags, fingerprints)."""

from __future__ import annotations

from maya_graph.music.normalize import (
    parse_share_path,
    parsed_from_query,
    slskd_external_id,
    split_artist_title,
    split_remix_version,
)


def test_parse_share_path_artist_album_title() -> None:
    parsed = parse_share_path(
        r"Music\Rick Astley\Never Gonna Give You Up 7inch\01 - Never Gonna Give You Up.flac"
    )
    assert parsed.artist == "Rick Astley"
    assert parsed.album == "Never Gonna Give You Up 7inch"
    assert parsed.base_title == "Never Gonna Give You Up"
    assert parsed.track_number == 1


def test_parse_share_path_artist_dash_title_without_dirs() -> None:
    parsed = parse_share_path(r"Downloads\Rick Astley - Never Gonna Give You Up.mp3")
    assert parsed.artist == "Rick Astley"
    assert parsed.base_title == "Never Gonna Give You Up"


def test_parse_share_path_does_not_invent_artist() -> None:
    parsed = parse_share_path(r"shared\01 - untitled.flac")
    assert parsed.artist is None
    assert parsed.base_title == "untitled"


def test_split_remix_and_version() -> None:
    base, remix, version = split_remix_version("Midnight City (Eric Prydz Remix) (Live)")
    assert base == "Midnight City"
    assert remix == "Eric Prydz"
    assert version == "live"


def test_discogs_numeric_suffix_stripped() -> None:
    artist, title = split_artist_title("Rick Astley (2) - Never Gonna Give You Up")
    assert artist == "Rick Astley"
    assert title == "Never Gonna Give You Up"


def test_parsed_from_query_artist_title() -> None:
    parsed = parsed_from_query("Rick Astley - Never Gonna Give You Up")
    assert parsed.artist == "Rick Astley"
    assert parsed.base_title == "Never Gonna Give You Up"


def test_slskd_external_id_is_stable_and_short() -> None:
    path = r"Music\Rick Astley\Whenever You Need Somebody\01 - Never Gonna Give You Up.flac"
    a = slskd_external_id("peer-one", path, 12_000_000)
    b = slskd_external_id("peer-one", path, 12_000_000)
    assert a == b
    assert len(a) <= 255
    assert a.startswith("peer-one:")
    assert path not in a
