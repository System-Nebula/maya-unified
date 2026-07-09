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
from services.music.set_playlist import build_playlist_from_set
from services.music.url_handler import detect_platform, index_music_url, index_music_url_sync

__all__ = [
    "ResolvedPlay",
    "build_playlist_from_resolution",
    "build_playlist_from_set",
    "detect_platform",
    "get_broker",
    "get_work_detail",
    "index_music_url",
    "index_music_url_sync",
    "ingest_bandcamp_items",
    "ingest_slskd_file",
    "lookup",
    "lookup_sync",
    "resolve_for_play",
    "resolve_for_play_sync",
]
