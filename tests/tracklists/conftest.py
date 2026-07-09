"""Shared tracklist contract assertions."""

from __future__ import annotations

from typing import Any

from maya_feeds.tracklist.protocol import TracklistPlatform, TracklistResolved
from services.music.set_types import ResolvedSet, SetEntry


def assert_set_contract(resolved: TracklistResolved | ResolvedSet) -> None:
    """Prove document → normalized set satisfies required field contract."""
    assert resolved.set_key
    assert resolved.title
    assert resolved.container_url
    assert resolved.container_schema
    assert len(resolved.entries) >= 1

    if isinstance(resolved, TracklistResolved):
        platform = TracklistPlatform(resolved.container_schema)
        assert platform.value == resolved.container_schema

    for entry in resolved.entries:
        assert entry.position >= 1
        assert entry.start_seconds >= 0
        if entry.end_seconds is not None:
            assert entry.end_seconds >= entry.start_seconds
        assert entry.label
        assert len(entry.source_refs) >= 1
        for ref in entry.source_refs:
            assert ref.schema_id
            assert ref.external_id


def assert_golden_entries(actual: list[Any], expected_rows: list[dict[str, Any]]) -> None:
    """Diff-friendly assertion for parsed tracklist entries vs golden JSON rows."""
    assert len(actual) == len(expected_rows), (
        f"expected {len(expected_rows)} entries, got {len(actual)}"
    )
    for i, (entry, row) in enumerate(zip(actual, expected_rows, strict=True)):
        assert entry.position == row["position"], f"entry {i + 1} position"
        assert entry.start_seconds == row["start_seconds"], f"entry {i + 1} start_seconds"
        assert entry.end_seconds == row["end_seconds"], f"entry {i + 1} end_seconds"
        assert entry.label == row["label"], f"entry {i + 1} label"
        assert entry.artist == row.get("artist"), f"entry {i + 1} artist"
        assert entry.title == row.get("title"), f"entry {i + 1} title"


def assert_entry_source_schemas(entry: SetEntry, expected: set[str]) -> None:
    schemas = {ref.schema_id for ref in entry.source_refs}
    assert schemas == expected
