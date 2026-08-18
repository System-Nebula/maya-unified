"""Platform-facing music ontology service.

Single entry point for agent tools, cmd executors, and HTTP routes. Wraps
``MusicQueryBroker`` and persists relational rows via maya-db.

DSN note: the graph tier reads ``MAYA_ONTOLOGY_DSN`` (asyncpg); relational
rows use ``DATABASE_URL`` (SQLAlchemy). For the hybrid tier both should point
at the same Postgres instance.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any

from maya_contracts import OntologyRef, SourceRefModel, TrackMetadata
from maya_graph.artist_bridge import slugify
from maya_graph.music.broker import MusicQueryBroker
from maya_graph.music.primitives import (
    ArtistRef,
    CanonicalWork,
    Recording,
    RecordingQuery,
    ResolutionEvent,
    SourceRef,
    WorkQuery,
    canonical_fingerprint,
    work_key_from_fingerprint,
)
from maya_graph.music.catalog import map_identity
from maya_graph.music.normalize import (
    parse_share_path,
    parsed_from_query,
    slskd_external_id,
)
from maya_graph.music.schemas.wikidata import WikidataSchema
from maya_graph.music.schemas import default_catalog_schemas
from sqlalchemy import func, select

logger = logging.getLogger(__name__)

_SPLIT_RE = re.compile(r"\s+[-–—:]\s+")
_CONFIDENCE_PLAY = 0.55
_CONFIDENCE_LOOKUP = 0.5


@dataclass(frozen=True, slots=True)
class ResolvedPlay:
    """Best playable URL from ontology resolution."""

    play_url: str
    title: str
    artist: str | None
    work_key: str | None
    confidence: float
    ontology: OntologyRef | None
    source_refs: tuple[SourceRefModel, ...]


def _parse_artist_title(query: str) -> tuple[str | None, str]:
    parts = _SPLIT_RE.split(query.strip(), maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return None, query.strip()


def _source_ref_models(work: CanonicalWork, recordings: tuple[Recording, ...]) -> list[SourceRefModel]:
    refs: list[SourceRefModel] = []
    seen: set[str] = set()
    for anchor in work.anchors:
        key = anchor.domain_key()
        if key not in seen:
            seen.add(key)
            refs.append(
                SourceRefModel(
                    schema_id=anchor.schema,
                    external_id=anchor.external_id,
                    url=anchor.url,
                )
            )
    for rec in recordings:
        key = rec.source.domain_key()
        if key not in seen:
            seen.add(key)
            refs.append(
                SourceRefModel(
                    schema_id=rec.source.schema,
                    external_id=rec.source.external_id,
                    url=rec.source.url or rec.webpage_url,
                )
            )
    return refs


def _pick_play_url(recording: Recording) -> str | None:
    for candidate in (recording.stream_url, recording.webpage_url, recording.source.url):
        if candidate and candidate.strip():
            return candidate.strip()
    schema = recording.source.schema
    ext_id = recording.source.external_id
    if schema == "yt" and ext_id:
        return f"https://youtu.be/{ext_id}"
    if schema == "bandcamp" and ext_id.startswith("http"):
        return ext_id
    return None


async def _persist_relational(event: ResolutionEvent) -> None:
    from maya_db.connection import async_session_factory
    from maya_db.models.music import MusicArtist, MusicPlatformLink, MusicTrack
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    work = event.work
    artist_name = work.artists[0].name if work.artists else None

    async with async_session_factory() as session:
        artist_id: uuid.UUID | None = None
        if artist_name:
            result = await session.execute(
                select(MusicArtist).where(func.lower(MusicArtist.name) == artist_name.lower())
            )
            artist = result.scalar_one_or_none()
            if artist is None:
                artist = MusicArtist(name=artist_name, sort_name=artist_name)
                session.add(artist)
                await session.flush()
            artist_id = artist.id

        fp = canonical_fingerprint(
            artist_name or "unknown",
            str(work.attrs.get("base_title") or work.label),
            work.attrs.get("remix"),
            work.attrs.get("version"),
        )
        track_attrs = {"source_schema": event.source_schema, **work.attrs}

        track_stmt = (
            pg_insert(MusicTrack)
            .values(
                id=uuid.uuid4(),
                title=work.label,
                base_title=work.attrs.get("base_title") or work.label,
                remix_name=work.attrs.get("remix"),
                remix_artist=work.attrs.get("remix"),
                version_type=work.attrs.get("version") or "original",
                isrc=work.attrs.get("isrc"),
                duration_seconds=work.attrs.get("duration_seconds"),
                canonical_fingerprint=fp[:255],
                canonical_work_key=work.key[:64] if work.key else None,
                primary_artist_id=artist_id,
                attrs=track_attrs,
            )
            .on_conflict_do_update(
                index_elements=["canonical_fingerprint"],
                set_={
                    "title": work.label,
                    "base_title": work.attrs.get("base_title") or work.label,
                    "canonical_work_key": work.key[:64] if work.key else None,
                    "primary_artist_id": artist_id,
                    "isrc": work.attrs.get("isrc"),
                    "attrs": MusicTrack.attrs.op("||")(pg_insert(MusicTrack).excluded.attrs),
                },
            )
            .returning(MusicTrack.id)
        )
        track_id = (await session.execute(track_stmt)).scalar_one()

        def _link_values(
            *,
            platform: str,
            external_id: str,
            url: str,
            extra_attrs: dict[str, Any],
        ) -> dict[str, Any]:
            return {
                "id": uuid.uuid4(),
                "entity_type": "track",
                "entity_id": track_id,
                "platform": platform[:32],
                "external_id": (external_id or "")[:255],
                "url": url,
                "confidence": event.confidence,
                "source": f"schema:{event.source_schema}",
                "attrs": extra_attrs,
            }

        async def _upsert_link(
            platform: str,
            external_id: str,
            url: str,
            extra_attrs: dict[str, Any],
        ) -> None:
            if not platform or not (external_id or url):
                return
            values = _link_values(
                platform=platform,
                external_id=external_id or url,
                url=url or f"{platform}:{external_id}",
                extra_attrs=extra_attrs,
            )
            link_stmt = (
                pg_insert(MusicPlatformLink)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["platform", "external_id"],
                    set_={
                        "url": values["url"],
                        "confidence": event.confidence,
                        "attrs": MusicPlatformLink.attrs.op("||")(
                            pg_insert(MusicPlatformLink).excluded.attrs
                        ),
                    },
                )
            )
            await session.execute(link_stmt)

        for recording in event.recordings:
            url = recording.source.url or recording.webpage_url or ""
            if not url and not recording.source.external_id:
                continue
            await _upsert_link(
                recording.source.schema,
                recording.source.external_id,
                url or recording.source.domain_key(),
                {
                    "title": recording.title,
                    "duration_seconds": recording.duration_seconds,
                    **recording.attrs,
                },
            )

        for anchor in work.anchors:
            await _upsert_link(
                anchor.schema,
                anchor.external_id,
                anchor.url or anchor.domain_key(),
                {"kind": "anchor"},
            )

        await session.commit()


_broker = MusicQueryBroker(
    schemas=default_catalog_schemas(),
    on_resolution=_persist_relational,
)
_wikidata = WikidataSchema()


def _extract_ytsearch(url_or_search: str) -> dict[str, Any]:
    import yt_dlp

    from services.discord.youtube_patch import _cookie_opts

    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        **_cookie_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url_or_search, download=False)
    if info and info.get("entries"):
        info = info["entries"][0]
    return info or {}


async def _ytdlp_recording_for_label(work: CanonicalWork) -> Recording | None:
    import asyncio

    label = (work.label or "").strip()
    if not label:
        return None
    try:
        info = await asyncio.to_thread(_extract_ytsearch, f"ytsearch1:{label}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("yt-dlp search failed for %r: %s", label, exc)
        return None
    video_id = info.get("id")
    if not video_id:
        return None
    webpage = info.get("webpage_url") or f"https://youtu.be/{video_id}"
    duration = info.get("duration")
    return Recording(
        source=SourceRef(schema="yt", external_id=str(video_id), url=webpage),
        title=str(info.get("title") or work.label),
        webpage_url=webpage,
        duration_seconds=int(duration) if duration else None,
        attrs={"source": "ytdlp"},
    )


async def _resolve_recording_for_work(work: CanonicalWork) -> Recording | None:
    """Graph recording → Wikidata P1651/P1552 → yt-dlp on canonical label."""
    recording = await _broker.resolve_recording(RecordingQuery(work_key=work.key))
    if recording is not None:
        return recording
    if work.key.startswith("wd:"):
        recs = await _wikidata.fetch_recordings(work)
        if recs:
            return recs[0]
    if work.label:
        return await _ytdlp_recording_for_label(work)
    return None


def get_broker() -> MusicQueryBroker:
    return _broker


def _ontology_configured() -> bool:
    """The hybrid tier needs a store. Without MAYA_ONTOLOGY_DSN/DATABASE_URL,
    every resolution would be a cold network call with nothing warmed — stay
    off and let legacy paths handle it (also keeps unit tests offline)."""
    return bool(os.getenv("MAYA_ONTOLOGY_DSN") or os.getenv("DATABASE_URL"))


async def lookup(query: str) -> TrackMetadata | None:
    text = (query or "").strip()
    if not text or not _ontology_configured():
        return None

    artist, title = _parse_artist_title(text)
    parsed = parsed_from_query(text, artist=artist, title=title)
    work_query = WorkQuery(text=parsed.base_title or title, artist=parsed.artist)
    candidates = await _broker.resolve_work(work_query)
    if not candidates or candidates[0].confidence < _CONFIDENCE_LOOKUP:
        return None

    best = candidates[0]
    work = best.work
    recordings: tuple[Recording, ...] = ()
    if best.node_id:
        rec = await _broker.resolve_recording(RecordingQuery(work_key=work.key))
        if rec is not None:
            recordings = (rec,)
    if not recordings and work.key.startswith("wd:"):
        recs = await _wikidata.fetch_recordings(work)
        if recs:
            recordings = (recs[0],)

    artist_name = work.artists[0].name if work.artists else artist
    return TrackMetadata(
        title=work.label,
        artist=artist_name,
        work_key=work.key,
        aliases=list(work.aliases),
        source_refs=_source_ref_models(work, recordings),
        confidence=best.confidence,
        matched_via="ontology",
    )


async def resolve_for_play(query: str) -> ResolvedPlay | None:
    text = (query or "").strip()
    if not text or not _ontology_configured():
        return None

    # Direct URL — skip ontology text resolution
    if text.startswith(("http://", "https://")):
        return None

    artist, title = _parse_artist_title(text)
    parsed = parsed_from_query(text, artist=artist, title=title)
    work_query = WorkQuery(text=parsed.base_title or title, artist=parsed.artist)
    candidates = await _broker.resolve_work(work_query)
    if not candidates or candidates[0].confidence < _CONFIDENCE_PLAY:
        return None

    best = candidates[0]
    work = best.work
    recording = await _resolve_recording_for_work(work)
    if recording is None:
        return None

    source_schema = "wd" if work.key.startswith("wd:") else "ytdlp"
    if recording.attrs.get("source") == "ytdlp":
        source_schema = "ytdlp"
    try:
        await _broker.ingest(
            ResolutionEvent(
                work=work,
                recordings=(recording,),
                source_schema=source_schema,
                confidence=best.confidence,
            )
        )
    except Exception as exc:  # noqa: BLE001 — graph warm must not block playback
        logger.warning("ontology ingest failed for %r: %s", query, exc)

    play_url = _pick_play_url(recording)
    if not play_url:
        return None

    artist_name = work.artists[0].name if work.artists else artist
    node_id = best.node_id
    return ResolvedPlay(
        play_url=play_url,
        title=recording.title or work.label,
        artist=artist_name,
        work_key=work.key,
        confidence=best.confidence,
        ontology=OntologyRef(
            work_key=work.key,
            work_node_id=node_id,
            recording_node_id=None,
            confidence=best.confidence,
        ),
        source_refs=tuple(_source_ref_models(work, (recording,))),
    )


async def get_work_detail(work_key: str) -> dict[str, Any] | None:
    key = (work_key or "").strip()
    if not key or ":" not in key:
        return None

    schema, _, external_id = key.partition(":")
    if schema == "fp":
        query = WorkQuery(fingerprint=external_id)
    else:
        query = WorkQuery(source_ref=SourceRef(schema=schema, external_id=external_id))

    candidates = await _broker.resolve_work(query)
    if not candidates:
        return None

    work = candidates[0].work
    recording = await _broker.resolve_recording(RecordingQuery(work_key=work.key))
    recordings = [recording] if recording else []
    return {
        "work_key": work.key,
        "label": work.label,
        "aliases": list(work.aliases),
        "anchors": [
            {"schema": a.schema, "external_id": a.external_id, "url": a.url}
            for a in work.anchors
        ],
        "artists": [{"slug": a.slug, "name": a.name} for a in work.artists],
        "confidence": candidates[0].confidence,
        "recordings": [
            {
                "schema": r.source.schema,
                "external_id": r.source.external_id,
                "title": r.title,
                "webpage_url": r.webpage_url,
                "stream_url": r.stream_url,
            }
            for r in recordings
        ],
    }


async def ingest_bandcamp_items(items: list[dict[str, Any]]) -> None:
    for item in items:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        artist = (item.get("artist") or "Unknown").strip()
        title = (item.get("title") or url).strip()
        fp = canonical_fingerprint(artist, title)
        work = CanonicalWork(
            key=work_key_from_fingerprint(fp),
            label=title,
            artists=(ArtistRef(slug=slugify(artist), name=artist),),
        )
        recording = Recording(
            source=SourceRef(schema="bandcamp", external_id=url, url=url),
            title=title,
            webpage_url=url,
        )
        await _broker.ingest(
            ResolutionEvent(
                work=work,
                recordings=(recording,),
                source_schema="bandcamp",
                confidence=0.75,
            )
        )


async def ingest_slskd_file(
    *,
    username: str,
    filename: str,
    artist_hint: str | None = None,
    title_hint: str | None = None,
    album_hint: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> None:
    """Ingest a verified Soulseek file using parsed names + catalog mapping.

    Peer username is stored on the recording only — never as the artist.
    """
    from maya_graph.music.normalize import ParsedTrack, merge_parsed

    parsed = parse_share_path(filename)
    parsed = merge_parsed(
        parsed,
        ParsedTrack(
            artist=artist_hint,
            title=title_hint,
            base_title=title_hint,
            album=album_hint,
        ),
    )
    if not parsed.artist or not (parsed.base_title or parsed.title):
        logger.info("slskd ingest skipped — no artist/title in %r", filename)
        return

    extra = dict(attrs or {})
    extra.update(
        {
            "username": username,
            "filename": filename,
            "album": parsed.album,
            "remix": parsed.remix,
            "version": parsed.version,
        }
    )
    work = await map_identity(parsed, _broker.schemas)
    recording = Recording(
        source=SourceRef(
            schema="slskd",
            external_id=slskd_external_id(
                username, filename, extra.get("size") if isinstance(extra.get("size"), int) else None
            ),
        ),
        title=work.label,
        attrs=extra,
    )
    await _broker.ingest(
        ResolutionEvent(
            work=work,
            recordings=(recording,),
            source_schema="catalog" if not work.key.startswith("fp:") else "slskd",
            confidence=0.85 if work.anchors else 0.6,
        )
    )


def lookup_sync(query: str) -> TrackMetadata | None:
    from services.async_bridge import run_sync

    return run_sync(lookup(query), timeout=20)


def resolve_for_play_sync(query: str) -> ResolvedPlay | None:
    from services.async_bridge import run_sync

    return run_sync(resolve_for_play(query), timeout=20)


def build_playlist_from_resolution(query: str, resolved: ResolvedPlay) -> dict[str, Any]:
    from services.dashboard.player import stream_src

    label = resolved.title or query
    play_q = resolved.play_url
    return {
        "type": "playlist",
        "title": label,
        "url": query,
        "tracks": [{"title": label, "query": play_q, "src": stream_src(play_q)}],
    }
