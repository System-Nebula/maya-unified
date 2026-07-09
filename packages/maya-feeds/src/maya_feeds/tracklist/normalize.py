"""Normalize parsed platform sets into TracklistResolved."""

from __future__ import annotations

from maya_contracts import SourceRefModel

from maya_feeds.apple_music import ParsedAppleSet, extract_album_id
from maya_feeds.tracklist.protocol import (
    PLATFORM_1001TL,
    PLATFORM_APPLE,
    PLATFORM_YOUTUBE,
    ParsedSetDocument,
    TracklistEntry,
    TracklistResolved,
    TracklistSourceRef,
)
from maya_feeds.tracklists_1001 import Parsed1001Set, extract_tracklist_id
from maya_feeds.youtube_setlist import ParsedYouTubeSet, extract_youtube_video_id


def _schema_for_url(url: str) -> str | None:
    from maya_feeds.tracklist.filter import classify_tracklist_url

    platform = classify_tracklist_url(url)
    if platform is None:
        return None
    return platform.value


def _external_id_for_url(url: str) -> str:
    vid = extract_youtube_video_id(url)
    if vid:
        return vid
    tl = extract_tracklist_id(url)
    if tl:
        return tl
    album = extract_album_id(url)
    if album:
        return album
    return url


def _source_ref(schema_id: str, external_id: str, *, url: str | None = None, confidence: float = 1.0) -> TracklistSourceRef:
    return TracklistSourceRef(schema_id=schema_id, external_id=external_id, url=url, confidence=confidence)


def _from_youtube(parsed: ParsedYouTubeSet) -> TracklistResolved:
    entries = [
        TracklistEntry(
            position=e.position,
            start_seconds=e.start_seconds,
            end_seconds=e.end_seconds,
            label=e.label,
            artist=e.artist,
            title=e.title,
            source_refs=[
                _source_ref(PLATFORM_YOUTUBE, f"{parsed.video_id}#{e.position}")
            ],
            attrs=dict(e.attrs),
        )
        for e in parsed.entries
    ]
    linked = [
        _source_ref(_schema_for_url(u), _external_id_for_url(u), url=u, confidence=0.9)
        for u in parsed.linked_urls
        if _schema_for_url(u)
    ]
    return TracklistResolved(
        set_key=f"{PLATFORM_YOUTUBE}:{parsed.video_id}",
        title=parsed.title,
        container_url=parsed.container_url,
        container_schema=PLATFORM_YOUTUBE,
        entries=entries,
        linked_sets=linked,
        attrs={"duration_seconds": parsed.duration_seconds},
    )


def _from_1001(parsed: Parsed1001Set) -> TracklistResolved:
    entries: list[TracklistEntry] = []
    for e in parsed.entries:
        row_id = e.row_id or f"row{e.position}"
        entries.append(
            TracklistEntry(
                position=e.position,
                start_seconds=e.start_seconds or 0,
                end_seconds=e.end_seconds,
                label=e.label,
                artist=e.artist,
                title=e.title,
                source_refs=[
                    _source_ref(
                        PLATFORM_1001TL,
                        f"{parsed.tracklist_id}:{row_id}",
                        url=parsed.container_url,
                    )
                ],
                attrs=dict(e.attrs),
            )
        )
    linked = [
        _source_ref(_schema_for_url(u), _external_id_for_url(u), url=u, confidence=0.9)
        for u in parsed.linked_urls
        if _schema_for_url(u)
    ]
    return TracklistResolved(
        set_key=f"{PLATFORM_1001TL}:{parsed.tracklist_id}",
        title=parsed.title,
        container_url=parsed.container_url,
        container_schema=PLATFORM_1001TL,
        entries=entries,
        linked_sets=linked,
        attrs=dict(parsed.attrs),
    )


def _from_apple(parsed: ParsedAppleSet) -> TracklistResolved:
    entries = [
        TracklistEntry(
            position=e.position,
            start_seconds=e.start_seconds or 0,
            end_seconds=e.end_seconds,
            label=e.label,
            artist=e.artist,
            title=e.title,
            source_refs=[
                _source_ref(PLATFORM_APPLE, e.track_id, url=parsed.container_url)
            ],
            attrs={"mix_context": True, **e.attrs},
        )
        for e in parsed.entries
    ]
    linked = [
        _source_ref(_schema_for_url(u), _external_id_for_url(u), url=u, confidence=0.9)
        for u in parsed.linked_urls
        if _schema_for_url(u)
    ]
    return TracklistResolved(
        set_key=f"{PLATFORM_APPLE}:{parsed.album_id}",
        title=parsed.title,
        container_url=parsed.container_url,
        container_schema=PLATFORM_APPLE,
        entries=entries,
        linked_sets=linked,
        attrs=dict(parsed.attrs),
    )


def parsed_to_tracklist_resolved(parsed: ParsedSetDocument) -> TracklistResolved:
    if isinstance(parsed, ParsedYouTubeSet):
        return _from_youtube(parsed)
    if isinstance(parsed, Parsed1001Set):
        return _from_1001(parsed)
    if isinstance(parsed, ParsedAppleSet):
        return _from_apple(parsed)
    raise TypeError(f"unsupported parsed set type: {type(parsed)!r}")


def tracklist_resolved_to_contract_refs(resolved: TracklistResolved) -> list[SourceRefModel]:
    """Convert linked sets to contract models (for url_handler bridge)."""
    return [
        SourceRefModel(
            schema_id=ref.schema_id,
            external_id=ref.external_id,
            url=ref.url,
            confidence=ref.confidence,
        )
        for ref in resolved.linked_sets
    ]
