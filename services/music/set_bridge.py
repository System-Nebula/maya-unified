"""Bridge tracklist parser output to ResolvedSet."""

from __future__ import annotations

from maya_contracts import SourceRefModel

from maya_feeds.tracklist.protocol import TracklistEntry, TracklistResolved, TracklistSourceRef
from services.music.set_types import ResolvedSet, SetEntry


def _to_source_ref(ref: TracklistSourceRef) -> SourceRefModel:
    return SourceRefModel(
        schema_id=ref.schema_id,
        external_id=ref.external_id,
        url=ref.url,
        confidence=ref.confidence,
    )


def _to_set_entry(entry: TracklistEntry) -> SetEntry:
    return SetEntry(
        position=entry.position,
        start_seconds=entry.start_seconds,
        end_seconds=entry.end_seconds,
        label=entry.label,
        artist=entry.artist,
        title=entry.title,
        source_refs=[_to_source_ref(r) for r in entry.source_refs],
        attrs=dict(entry.attrs),
    )


def tracklist_to_resolved_set(resolved: TracklistResolved) -> ResolvedSet:
    return ResolvedSet(
        set_key=resolved.set_key,
        title=resolved.title,
        container_url=resolved.container_url,
        container_schema=resolved.container_schema,
        entries=[_to_set_entry(e) for e in resolved.entries],
        linked_sets=[_to_source_ref(r) for r in resolved.linked_sets],
        attrs=dict(resolved.attrs),
    )
