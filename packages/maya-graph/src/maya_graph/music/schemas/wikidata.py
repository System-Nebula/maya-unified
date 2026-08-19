"""Wikidata source schema — canonical song/work identity via wbsearchentities.

Identity search disambiguates free text to a canonical work (``wd:Q…``).
Recording enrichment follows P1651 (YouTube video ID) on the work and on
P1552 (has characteristic) linked entities — e.g. YouTube auto-generated
videos for Despacito (Q130464775 → t3IyUATcAbE).

Best-effort by contract — timeouts and HTTP failures yield empty results.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx

from maya_graph.music.normalize import artist_refs
from maya_graph.music.otel import TRACER, record_http
from maya_graph.music.primitives import (
    CanonicalWork,
    Recording,
    SourceRef,
    WorkQuery,
)

logger = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "maya-unified-music/1.0 (+https://github.com/System-Nebula/maya-unified)"
ENTITY_URL = "https://www.wikidata.org/wiki/{qid}"

# Wikidata properties used for playable recording enrichment.
P_INSTANCE_OF = "P31"
P_HAS_CHARACTERISTIC = "P1552"
P_YOUTUBE_VIDEO_ID = "P1651"
P_DURATION = "P2047"
P_VIEW_COUNT = "P5436"
P_PERFORMER = "P175"
P_MB_RECORDING = "P4404"
P_MB_RELEASE_GROUP = "P436"
P_MB_WORK = "P435"
P_MB_ARTIST = "P434"
P_DISCOGS_MASTER = "P1954"
P_DISCOGS_ARTIST = "P2206"
P_SPOTIFY_TRACK = "P2207"
P_APPLE_ALBUM = "P2281"
P_ITUNES_ARTIST = "P2850"

_SEARCH_DELAY_SEC = 1.5
_SEARCH_TIMEOUT_SEC = 12.0

# "instance of" (P31) QIDs that count as a song/track for our purposes.
_SONG_LIKE_QIDS = {
    "Q7366",  # song
    "Q134556",  # single
    "Q2743",  # musical composition (fallback, broader)
    "Q105543609",  # music release
}

# Album / studio-album P31s for release-group mapping (Brat CD, LPs).
_ALBUM_LIKE_QIDS = {
    "Q482994",  # album
    "Q208569",  # studio album
    "Q41582469",  # musical work / album class used on some items
    "Q3307153",  # double album
}

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _catalog_anchors(qid: str, claims: dict[str, list]) -> list[SourceRef]:
    """Resurface MusicBrainz / Discogs / Apple / Spotify ids stored on Wikidata."""
    anchors: list[SourceRef] = [
        SourceRef(schema="wd", external_id=qid, url=ENTITY_URL.format(qid=qid)),
    ]
    specs = (
        (P_MB_RECORDING, "mb", "recording/{id}", "https://musicbrainz.org/recording/{id}"),
        (P_MB_RELEASE_GROUP, "mb", "release-group/{id}", "https://musicbrainz.org/release-group/{id}"),
        (P_MB_WORK, "mb", "work/{id}", "https://musicbrainz.org/work/{id}"),
        (P_MB_ARTIST, "mb", "artist/{id}", "https://musicbrainz.org/artist/{id}"),
        (P_DISCOGS_MASTER, "discogs", "master/{id}", "https://www.discogs.com/master/{id}"),
        (P_DISCOGS_ARTIST, "discogs", "artist/{id}", "https://www.discogs.com/artist/{id}"),
        (P_SPOTIFY_TRACK, "spotify", "{id}", "https://open.spotify.com/track/{id}"),
        (P_APPLE_ALBUM, "apple_music", "album/{id}", "https://music.apple.com/album/{id}"),
        (P_ITUNES_ARTIST, "apple_music", "artist/{id}", None),
    )
    for prop, schema, id_fmt, url_fmt in specs:
        for value in _claim_string_values(claims, prop):
            external_id = id_fmt.format(id=value)
            anchors.append(
                SourceRef(
                    schema=schema,
                    external_id=external_id,
                    url=url_fmt.format(id=value) if url_fmt else None,
                )
            )
    return anchors

_last_search_at: float = 0.0
_rate_lock = asyncio.Lock()


async def _rate_limit() -> None:
    global _last_search_at
    async with _rate_lock:
        elapsed = time.monotonic() - _last_search_at
        if elapsed < _SEARCH_DELAY_SEC:
            await asyncio.sleep(_SEARCH_DELAY_SEC - elapsed)
        _last_search_at = time.monotonic()


def _name_matches(expected: str, actual: str) -> bool:
    left, right = expected.casefold().strip(), actual.casefold().strip()
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _entity_label(entity: dict[str, Any]) -> str | None:
    """English, then multilingual ``mul``, then any remaining label."""
    labels = entity.get("labels") or {}
    for lang in ("en", "mul"):
        value = (labels.get(lang) or {}).get("value")
        if value:
            return str(value)
    for row in labels.values():
        if isinstance(row, dict) and row.get("value"):
            return str(row["value"])
    return None


def _qid_from_work_key(work_key: str) -> str | None:
    if not work_key.startswith("wd:"):
        return None
    qid = work_key[3:].strip()
    return qid or None


def _entity_claims(entity: dict[str, Any]) -> dict[str, list]:
    return entity.get("claims") or {}


def _claim_entity_ids(claims: dict[str, list], prop: str) -> list[str]:
    out: list[str] = []
    for claim in claims.get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        qid = value.get("id")
        if qid:
            out.append(qid)
    return out


def _claim_string_values(claims: dict[str, list], prop: str) -> list[str]:
    out: list[str] = []
    for claim in claims.get(prop, []):
        datavalue = claim.get("mainsnak", {}).get("datavalue", {})
        if datavalue.get("type") != "string":
            continue
        text = datavalue.get("value")
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
    return out


def _claim_quantity(claims: dict[str, list], prop: str) -> float | None:
    for claim in claims.get(prop, []):
        datavalue = claim.get("mainsnak", {}).get("datavalue", {})
        if datavalue.get("type") != "quantity":
            continue
        amount = datavalue.get("value", {}).get("amount")
        if amount is None:
            continue
        try:
            return float(str(amount).lstrip("+"))
        except ValueError:
            continue
    return None


def _recording_from_video_id(
    video_id: str,
    *,
    title: str,
    duration_seconds: int | None = None,
    attrs: dict[str, Any] | None = None,
) -> Recording | None:
    if not _YT_ID_RE.match(video_id):
        return None
    webpage = f"https://youtu.be/{video_id}"
    return Recording(
        source=SourceRef(schema="yt", external_id=video_id, url=webpage),
        title=title,
        webpage_url=webpage,
        duration_seconds=duration_seconds,
        attrs={**(attrs or {}), "source": "wikidata"},
    )


class WikidataSchema:
    """SourceSchema adapter for Wikidata (schema_id ``wd``)."""

    schema_id = "wd"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def search_work(self, query: WorkQuery) -> list[CanonicalWork]:
        """Title-only wbsearchentities; artist is used to rank song-like hits.

        Concatenating ``"{artist} {title}"`` often returns zero Wikidata hits
        (e.g. Rick Astley + Never Gonna Give You Up). Search the title, skip
        non-song P31s, then prefer a matching P175 performer.
        """
        title = (query.text or "").strip()
        artist = (query.artist or "").strip()
        if not title and artist:
            title, artist = artist, ""
        if not title:
            return []
        return await self._run_search(title, artist=artist, instance_qids=_SONG_LIKE_QIDS)

    async def search_release(self, query: WorkQuery) -> list[CanonicalWork]:
        """Album/studio-album identity (``Brat (album)`` before bare title)."""
        title = (query.text or "").strip()
        artist = (query.artist or "").strip()
        if not title:
            return []
        for text in (f"{title} (album)", title):
            works = await self._run_search(
                text, artist=artist, instance_qids=_ALBUM_LIKE_QIDS
            )
            if works:
                return works
        return []

    async def _run_search(
        self,
        text: str,
        *,
        artist: str,
        instance_qids: set[str],
    ) -> list[CanonicalWork]:
        try:
            if self._client is None:
                await _rate_limit()
            if self._client is not None:
                return await self._search(
                    self._client, text, artist=artist, instance_qids=instance_qids
                )
            async with httpx.AsyncClient(
                timeout=_SEARCH_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                return await self._search(
                    client, text, artist=artist, instance_qids=instance_qids
                )
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("wikidata search failed for %r: %s", text, exc)
            return []

    async def fetch_recordings(self, work: CanonicalWork) -> list[Recording]:
        """YouTube recordings from P1651 on the work and P1552-linked entities."""
        qid = _qid_from_work_key(work.key)
        if not qid:
            return []
        try:
            if self._client is not None:
                return await self._fetch_recordings_for_qid(self._client, qid, work.label)
            async with httpx.AsyncClient(
                timeout=_SEARCH_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                return await self._fetch_recordings_for_qid(client, qid, work.label)
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("wikidata recording fetch failed for %s: %s", work.key, exc)
            return []

    async def fetch_recording(self, ref: SourceRef) -> Recording | None:
        if ref.schema != "wd":
            return None
        work = CanonicalWork(
            key=f"wd:{ref.external_id}",
            label=ref.external_id,
            anchors=(ref,),
        )
        recordings = await self.fetch_recordings(work)
        return recordings[0] if recordings else None

    async def _search(
        self,
        client: httpx.AsyncClient,
        text: str,
        *,
        artist: str = "",
        instance_qids: set[str] | None = None,
    ) -> list[CanonicalWork]:
        allowed = instance_qids or _SONG_LIKE_QIDS
        with TRACER.start_as_current_span("catalog.http.wd") as span:
            span.set_attribute("catalog.query", text[:160])
            resp = await client.get(
                WIKIDATA_API,
                params={
                    "action": "wbsearchentities",
                    "format": "json",
                    "language": "en",
                    "search": text,
                    "type": "item",
                    "limit": 10,
                },
            )
            if resp.status_code != 200:
                record_http(resp.status_code, error=f"HTTP {resp.status_code}", hits=0)
                return []
            candidates = [
                row
                for row in (resp.json().get("search") or [])
                if isinstance(row, dict) and row.get("id")
            ]
            record_http(resp.status_code, hits=len(candidates))
        qids = [str(row["id"]) for row in candidates]
        entities = await self._fetch_entities(client, qids)
        ranked: list[tuple[int, CanonicalWork, list[str]]] = []
        performer_qids: list[str] = []
        for candidate in candidates:
            qid = str(candidate["id"])
            entity = entities.get(qid) or {}
            if entity.get("missing"):
                continue
            claims = _entity_claims(entity)
            p31 = set(_claim_entity_ids(claims, P_INSTANCE_OF))
            if not (p31 & allowed):
                continue
            pqids = _claim_entity_ids(claims, P_PERFORMER)[:3]
            performer_qids.extend(pqids)
            ranked.append(
                (
                    0,
                    CanonicalWork(
                        key=f"wd:{qid}",
                        label=candidate.get("label", text),
                        aliases=tuple(candidate.get("aliases") or []),
                        anchors=tuple(_catalog_anchors(qid, claims)),
                        attrs={"description": candidate.get("description", "")},
                    ),
                    pqids,
                )
            )
        if not ranked:
            return []
        performers = await self._fetch_entities(client, list(dict.fromkeys(performer_qids)))
        works: list[CanonicalWork] = []
        for _, work, pqids in ranked:
            names: list[str] = []
            for pqid in pqids:
                label = _entity_label(performers.get(pqid) or {})
                if label:
                    names.append(label)
            if artist:
                names.sort(key=lambda n: (0 if _name_matches(artist, n) else 1))
            filled = CanonicalWork(
                key=work.key,
                label=work.label,
                aliases=work.aliases,
                anchors=work.anchors,
                artists=artist_refs(*names),
                attrs=work.attrs,
            )
            works.append(filled)
        if artist:
            for work in works:
                if any(_name_matches(artist, a.name) for a in work.artists):
                    return [work]
            needle = artist.casefold()
            for work in works:
                if needle in str(work.attrs.get("description") or "").casefold():
                    return [work]
        return works[:1]

    async def _fetch_entity_p31(self, client: httpx.AsyncClient, qid: str) -> set[str]:
        resp = await client.get(
            WIKIDATA_API,
            params={
                "action": "wbgetclaims",
                "format": "json",
                "entity": qid,
                "property": P_INSTANCE_OF,
            },
        )
        if resp.status_code != 200:
            return set()
        claims = resp.json().get("claims", {}).get(P_INSTANCE_OF, [])
        out: set[str] = set()
        for claim in claims:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            instance_qid = value.get("id")
            if instance_qid:
                out.add(instance_qid)
        return out

    async def _fetch_entities(
        self, client: httpx.AsyncClient, qids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not qids:
            return {}
        resp = await client.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(qids),
                "props": "claims|labels",
            },
        )
        if resp.status_code != 200:
            return {}
        return resp.json().get("entities") or {}

    async def _fetch_recordings_for_qid(
        self, client: httpx.AsyncClient, qid: str, label: str
    ) -> list[Recording]:
        entities = await self._fetch_entities(client, [qid])
        work_entity = entities.get(qid) or {}
        work_claims = _entity_claims(work_entity)

        # Collect characteristic entity QIDs (P1552) — YouTube auto-generated videos, etc.
        char_qids = _claim_entity_ids(work_claims, P_HAS_CHARACTERISTIC)
        char_entities = await self._fetch_entities(client, char_qids) if char_qids else {}

        candidates: list[tuple[float, Recording]] = []

        def add_from_claims(claims: dict[str, list], title: str, *, rank_boost: float = 0.0) -> None:
            duration_raw = _claim_quantity(claims, P_DURATION)
            duration = int(duration_raw) if duration_raw is not None else None
            views = _claim_quantity(claims, P_VIEW_COUNT) or 0.0
            for video_id in _claim_string_values(claims, P_YOUTUBE_VIDEO_ID):
                rec = _recording_from_video_id(
                    video_id,
                    title=title,
                    duration_seconds=duration,
                    attrs={"wikidata_qid": qid},
                )
                if rec is not None:
                    candidates.append((views + rank_boost, rec))

        # Direct P1651 on the work entity (lower boost than characteristic-linked).
        add_from_claims(work_claims, label, rank_boost=0.0)

        # P1552 → linked entity P1651 (preferred for auto-generated official streams).
        for char_qid, entity in char_entities.items():
            if entity.get("missing"):
                continue
            char_label = _entity_label(entity) or label
            add_from_claims(_entity_claims(entity), char_label, rank_boost=1.0)

        if not candidates:
            return []

        # Tie-break: highest P5436 view count; characteristic-linked wins on equal views.
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        seen: set[str] = set()
        out: list[Recording] = []
        for _, rec in candidates:
            vid = rec.source.external_id
            if vid in seen:
                continue
            seen.add(vid)
            out.append(rec)
        return out
