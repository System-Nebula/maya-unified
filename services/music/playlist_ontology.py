"""Fan a YouTube/album playlist out to catalog platforms and the ontology graph.

YouTube still supplies the playable URLs. Apple Music album lookup (track-title
overlap) supplies the artist so short titles like ``listen.`` are not mapped
as Beyoncé. Deep mode then walks Wikidata / MusicBrainz / Discogs / Apple for
each track and writes ResolutionEvents.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from rapidfuzz import fuzz
from rapidfuzz import utils as fuzz_utils

from maya_graph.music.catalog import map_identity
from maya_graph.music.normalize import ParsedTrack
from maya_graph.music.primitives import CanonicalWork, Recording, ResolutionEvent, SourceRef
from maya_graph.music.schemas import default_catalog_schemas
from maya_graph.music.schemas.itunes import (
    collection_id_from_album_work,
    lookup_collection_songs,
    search_album,
)
from services.discord.playlist import PlaylistExpansion
from services.tracing import corr_span

logger = logging.getLogger(__name__)

_TITLE_MATCH = 82.0
_ALBUM_OVERLAP = 0.5
_TRAILING_PUNCT = re.compile(r"[.\u2026]+$")


@dataclass
class PlaylistTrackOntology:
    title: str
    url: str
    video_id: str | None
    artist: str | None
    work_key: str | None
    work: CanonicalWork | None
    source_refs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PlaylistOntology:
    artist: str | None
    album_title: str
    album_work: CanonicalWork | None
    overlap: float
    tracks: list[PlaylistTrackOntology]
    source_refs: list[dict[str, Any]] = field(default_factory=list)


def _norm_title(value: str) -> str:
    return _TRAILING_PUNCT.sub("", (value or "").strip()).strip()


def _title_ratio(left: str, right: str) -> float:
    a, b = _norm_title(left), _norm_title(right)
    if not a or not b:
        return 0.0
    return float(fuzz.token_set_ratio(a, b, processor=fuzz_utils.default_process))


def _video_id_for(expansion: PlaylistExpansion, index: int, url: str) -> str | None:
    if index < len(expansion.video_ids) and expansion.video_ids[index]:
        return expansion.video_ids[index]
    parsed = urlparse(url)
    vid = (parse_qs(parsed.query).get("v") or [None])[0]
    if vid:
        return str(vid)
    if "youtu.be/" in url:
        return url.rsplit("/", 1)[-1][:11]
    return None


def _ref_payload(ref: SourceRef, *, confidence: float = 0.9) -> dict[str, Any]:
    return {
        "schema_id": ref.schema,
        "external_id": ref.external_id,
        "url": ref.url,
        "confidence": confidence,
    }


def _best_song(title: str, songs: list[CanonicalWork]) -> CanonicalWork | None:
    ranked = sorted(
        (( _title_ratio(title, song.label), song) for song in songs),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not ranked:
        return None
    score, song = ranked[0]
    return song if score >= _TITLE_MATCH else None


def _yt_ref(video_id: str | None, url: str) -> SourceRef | None:
    if not video_id:
        return None
    return SourceRef(schema="yt", external_id=video_id, url=url)


def _merge_yt_anchor(work: CanonicalWork, yt: SourceRef | None) -> CanonicalWork:
    if yt is None:
        return work
    existing = {a.domain_key() for a in work.anchors}
    if yt.domain_key() in existing:
        return work
    return CanonicalWork(
        key=work.key,
        label=work.label,
        aliases=work.aliases,
        anchors=work.anchors + (yt,),
        artists=work.artists,
        attrs=dict(work.attrs),
    )


async def _pick_apple_album(
    expansion: PlaylistExpansion,
) -> tuple[CanonicalWork | None, list[CanonicalWork], float]:
    album_title = (expansion.title or "").strip()
    if not album_title:
        return None, [], 0.0
    artist_hint = (expansion.artist or "").strip()
    albums = await search_album(artist_hint, album_title)
    if not albums and artist_hint:
        albums = await search_album("", album_title)
    yt_titles = [title for _url, title in expansion.tracks]
    best: tuple[float, CanonicalWork | None, list[CanonicalWork]] = (0.0, None, [])
    seen: set[str] = set()
    for album in albums:
        cid = collection_id_from_album_work(album)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        album_work, songs = await lookup_collection_songs(cid)
        if not songs:
            continue
        hits = sum(
            1 for title in yt_titles if _best_song(title, songs) is not None
        )
        overlap = hits / len(yt_titles) if yt_titles else 0.0
        candidate = album_work or album
        if overlap > best[0]:
            best = (overlap, candidate, songs)
    if best[0] < _ALBUM_OVERLAP:
        return None, [], best[0]
    return best[1], best[2], best[0]


async def resolve_playlist_ontology(
    url: str,
    expansion: PlaylistExpansion,
    *,
    deep: bool = False,
    ingest: bool = False,
) -> PlaylistOntology | None:
    """Match a YouTube playlist onto Apple Music, then optionally every catalog."""
    if expansion is None or not expansion.tracks:
        return None
    with corr_span(
        "play.ontology_fanout",
        url=url,
        title=expansion.title or "",
        deep=deep,
        track_count=len(expansion.tracks),
    ) as span:
        album_work, songs, overlap = await _pick_apple_album(expansion)
        span.set_attribute("ontology.apple_overlap", overlap)
        if album_work is None:
            span.set_attribute("ontology.matched", False)
            return None
        artist = album_work.artists[0].name if album_work.artists else expansion.artist
        span.set_attribute("ontology.artist", artist or "")
        span.set_attribute("ontology.album_key", album_work.key)
        span.set_attribute("ontology.matched", True)

        schemas = default_catalog_schemas() if deep else ()
        album_mapped = album_work
        if deep:
            album_parsed = ParsedTrack(
                artist=artist,
                title=album_work.label,
                base_title=album_work.label,
                album=album_work.label,
            )
            album_mapped = await map_identity(
                album_parsed, schemas, extra_works=(album_work,)
            )
            album_mapped = CanonicalWork(
                key=album_mapped.key,
                label=album_mapped.label,
                aliases=album_mapped.aliases,
                anchors=album_mapped.anchors,
                artists=album_mapped.artists or album_work.artists,
                attrs={**album_mapped.attrs, "kind": "album"},
            )

        tracks: list[PlaylistTrackOntology] = []
        events: list[ResolutionEvent] = []
        for index, (track_url, title) in enumerate(expansion.tracks):
            video_id = _video_id_for(expansion, index, track_url)
            apple_song = _best_song(title, songs)
            parsed = ParsedTrack(
                artist=artist,
                title=_norm_title(title) or title,
                base_title=_norm_title(title) or title,
                album=album_work.label,
            )
            extra = tuple(w for w in (apple_song,) if w is not None)
            if deep:
                work = await map_identity(parsed, schemas, extra_works=extra)
            elif apple_song is not None:
                work = apple_song
            else:
                work = CanonicalWork(
                    key="fp:unmapped",
                    label=title,
                    artists=album_work.artists,
                    attrs={"unmapped": True, "album": album_work.label},
                )
            yt = _yt_ref(video_id, track_url)
            work = _merge_yt_anchor(work, yt)
            refs = [_ref_payload(a) for a in work.anchors]
            tracks.append(
                PlaylistTrackOntology(
                    title=work.label or title,
                    url=track_url,
                    video_id=video_id,
                    artist=artist,
                    work_key=work.key,
                    work=work,
                    source_refs=refs,
                )
            )
            recording = None
            if yt is not None:
                recording = Recording(
                    source=yt,
                    title=work.label or title,
                    webpage_url=track_url,
                    attrs={"playlist_url": url, "position": index + 1},
                )
            events.append(
                ResolutionEvent(
                    work=work,
                    recordings=(recording,) if recording is not None else (),
                    source_schema="catalog" if not work.key.startswith("fp:") else "yt",
                    confidence=0.85 if apple_song is not None else 0.6,
                )
            )

        if ingest and (os.getenv("MAYA_ONTOLOGY_DSN") or os.getenv("DATABASE_URL")):
            from services.music.ontology import get_broker

            broker = get_broker()
            try:
                await broker.ingest(
                    ResolutionEvent(
                        work=album_mapped,
                        recordings=(),
                        source_schema="catalog",
                        confidence=0.9,
                    )
                )
                for event in events:
                    await broker.ingest(event)
            except Exception:  # noqa: BLE001
                logger.debug("playlist ontology ingest failed", exc_info=True)

        span.set_attribute("ontology.track_mapped", sum(1 for t in tracks if t.work_key and not str(t.work_key).startswith("fp:")))
        album_refs = [_ref_payload(a) for a in album_mapped.anchors]
        if expansion.playlist_id:
            album_refs.append(
                _ref_payload(
                    SourceRef(
                        schema="yt",
                        external_id=f"playlist/{expansion.playlist_id}",
                        url=url,
                    )
                )
            )
        return PlaylistOntology(
            artist=artist,
            album_title=album_mapped.label or expansion.title,
            album_work=album_mapped,
            overlap=overlap,
            tracks=tracks,
            source_refs=album_refs,
        )


def apply_playlist_ontology(artifact: dict[str, Any], onto: PlaylistOntology) -> dict[str, Any]:
    """Stamp artist / work keys / platform links onto a sticky-player artifact."""
    out = dict(artifact)
    out["artist"] = onto.artist
    out["title"] = onto.album_title or artifact.get("title")
    if onto.album_work is not None:
        out["work_key"] = onto.album_work.key
    out["source_refs"] = onto.source_refs
    rows = []
    for index, track in enumerate(artifact.get("tracks") or []):
        row = dict(track)
        mapped = onto.tracks[index] if index < len(onto.tracks) else None
        if mapped is not None:
            row["title"] = mapped.title or row.get("title")
            row["artist"] = mapped.artist
            row["work_key"] = mapped.work_key
            row["source_refs"] = mapped.source_refs
        rows.append(row)
    out["tracks"] = rows
    return out
