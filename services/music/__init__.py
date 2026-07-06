"""Music domain services (ontology lookup/resolution)."""

from services.music.ontology import (
    ResolvedPlay,
    build_playlist_from_resolution,
    get_broker,
    get_work_detail,
    ingest_bandcamp_items,
    ingest_slskd_file,
    lookup,
    lookup_sync,
    resolve_for_play,
    resolve_for_play_sync,
)

__all__ = [
    "ResolvedPlay",
    "build_playlist_from_resolution",
    "get_broker",
    "get_work_detail",
    "ingest_bandcamp_items",
    "ingest_slskd_file",
    "lookup",
    "lookup_sync",
    "resolve_for_play",
    "resolve_for_play_sync",
]
