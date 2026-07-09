"""Tests for virtual DJ set playlist expansion."""

from __future__ import annotations

from services.music.set_playlist import build_playlist_from_set, build_set_artifact
from services.music.url_handler import PLATFORM_YOUTUBE, ResolvedSet, SetEntry
from tests.helpers.music_set_fixtures import andrea_resolved_set, load_andrea_expected


def test_build_playlist_from_set_seek_offsets():
    resolved = ResolvedSet(
        set_key=f"{PLATFORM_YOUTUBE}:u1NHX9FcHVw",
        title="Techno Mix",
        container_url="https://www.youtube.com/watch?v=u1NHX9FcHVw",
        container_schema=PLATFORM_YOUTUBE,
        entries=[
            SetEntry(
                position=1,
                start_seconds=0,
                end_seconds=102,
                label="Hard Bounce",
                artist=None,
                title="Hard Bounce",
                work_key="fp:abc123",
            ),
            SetEntry(
                position=2,
                start_seconds=102,
                end_seconds=153,
                label="The Ladies Gon Feel Me - Joann",
                artist="The Ladies Gon Feel Me",
                title="Joann",
                work_key="fp:def456",
            ),
        ],
    )
    artifact = build_playlist_from_set("https://www.youtube.com/watch?v=u1NHX9FcHVw", resolved)
    assert artifact["type"] == "playlist"
    assert artifact["presentation"] == "set"
    assert artifact["mode"] == "live_set"
    assert artifact["set_key"] == f"{PLATFORM_YOUTUBE}:u1NHX9FcHVw"
    assert artifact["video_id"] == "u1NHX9FcHVw"
    assert len(artifact["entries"]) == 2
    assert len(artifact["tracks"]) == 2
    assert artifact["tracks"][0]["start_offset"] == 0
    assert artifact["tracks"][1]["start_offset"] == 102
    assert artifact["tracks"][0]["work_key"] == "fp:abc123"
    assert artifact["tracks"][0]["query"] == resolved.container_url


def test_build_set_artifact_andrea_golden():
    golden = load_andrea_expected()
    resolved = andrea_resolved_set()
    artifact = build_set_artifact("https://www.youtube.com/watch?v=u1NHX9FcHVw", resolved)
    assert artifact["presentation"] == "set"
    assert artifact["entries"][0]["label"] == golden["entries"][0]["label"]
    assert artifact["entries"][0]["start_seconds"] == golden["entries"][0]["start_seconds"]
    assert len(artifact["entries"]) == 26
