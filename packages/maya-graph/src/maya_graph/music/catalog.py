"""Map a parsed track onto catalog source schemas (MusicBrainz, Discogs, Apple).

Walks every registered schema (best-effort) and merges anchors onto one
CanonicalWork so the Postgres graph stores strong artist/title plus external
ids. Falls back to an internal ``fp:`` work when catalogs miss.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rapidfuzz import fuzz
from rapidfuzz import utils as fuzz_utils

from maya_graph.music.normalize import ParsedTrack, artist_refs, fingerprint_work
from maya_graph.music.primitives import CanonicalWork, SourceRef, WorkQuery
from maya_graph.music.schemas.base import SourceSchema

_TITLE_MIN = 0.72
_ARTIST_MIN = 0.62

# Preference when several catalogs hit: keep this work.key, merge the rest as anchors.
_KEY_RANK = ("wd", "mb", "discogs", "apple_music", "spotify", "fp")


def name_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return (
        fuzz.token_set_ratio(left, right, processor=fuzz_utils.default_process) / 100.0
    )


def _title_score(parsed: ParsedTrack, work: CanonicalWork) -> float:
    query = parsed.base_title or parsed.title or ""
    aliases = list(work.aliases) + [work.label]
    return max((name_score(query, alias) for alias in aliases), default=0.0)


def _artist_score(parsed: ParsedTrack, work: CanonicalWork) -> float:
    if not parsed.artist:
        return 1.0
    names = [a.name for a in work.artists if a.name]
    if names:
        return max(name_score(parsed.artist, name) for name in names)
    return name_score(parsed.artist, work.label)


def _key_rank(key: str) -> int:
    schema = key.split(":", 1)[0]
    try:
        return _KEY_RANK.index(schema)
    except ValueError:
        return len(_KEY_RANK)


def _merge_anchors(*groups: tuple[SourceRef, ...]) -> tuple[SourceRef, ...]:
    seen: set[str] = set()
    out: list[SourceRef] = []
    for group in groups:
        for ref in group:
            key = ref.domain_key()
            if not ref.schema or not ref.external_id or key in seen:
                continue
            seen.add(key)
            out.append(ref)
    return tuple(out)


def _accept(parsed: ParsedTrack, work: CanonicalWork) -> bool:
    if _title_score(parsed, work) < _TITLE_MIN:
        return False
    if parsed.artist and work.artists and _artist_score(parsed, work) < _ARTIST_MIN:
        return False
    return True


async def map_identity(
    parsed: ParsedTrack,
    schemas: Sequence[SourceSchema],
) -> CanonicalWork:
    """Resolve parsed strings against catalogs; ``fp:`` if nothing matches.

    Catalogs that pass the title/artist threshold contribute anchors. The
    work key comes from the highest-ranked accepted catalog (Wikidata, then
    MusicBrainz, Discogs, Apple Music).
    """
    fallback = fingerprint_work(parsed)
    accepted: list[CanonicalWork] = []
    for schema in schemas:
        try:
            works = await schema.search_work(
                WorkQuery(
                    text=parsed.base_title or parsed.title,
                    artist=parsed.artist,
                )
            )
        except Exception:
            continue
        for work in works:
            if _accept(parsed, work):
                accepted.append(work)
                break

    if not accepted and fallback is not None:
        return fallback
    if not accepted:
        label = parsed.display_title() or "unknown"
        return CanonicalWork(
            key="fp:unknown",
            label=label,
            artists=artist_refs(parsed.artist),
            attrs={"unmapped": True, "album": parsed.album},
        )

    accepted.sort(key=lambda work: _key_rank(work.key))
    primary = accepted[0]
    aliases = list(primary.aliases)
    for work in accepted:
        if work.label and work.label not in aliases:
            aliases.append(work.label)
        for alias in work.aliases:
            if alias and alias not in aliases:
                aliases.append(alias)
    if fallback is not None and fallback.key not in aliases:
        aliases.append(fallback.key)

    artists = primary.artists or (fallback.artists if fallback else artist_refs(parsed.artist))
    attrs: dict[str, Any] = {**(fallback.attrs if fallback else {}), **primary.attrs}
    attrs["album"] = primary.attrs.get("album") or parsed.album
    attrs["catalog_schemas"] = [work.key.split(":", 1)[0] for work in accepted]
    if parsed.isrc:
        attrs["isrc"] = parsed.isrc
    extra_anchors = ()
    if parsed.mb_recording_id:
        extra_anchors = (
            SourceRef(
                schema="mb",
                external_id=f"recording/{parsed.mb_recording_id}",
                url=f"https://musicbrainz.org/recording/{parsed.mb_recording_id}",
            ),
        )
    if parsed.isrc:
        extra_anchors = extra_anchors + (
            SourceRef(schema="isrc", external_id=parsed.isrc),
        )
    return CanonicalWork(
        key=primary.key,
        label=primary.label or parsed.display_title() or primary.key,
        aliases=tuple(aliases),
        anchors=_merge_anchors(primary.anchors, *(w.anchors for w in accepted[1:]), extra_anchors),
        artists=artists,
        attrs=attrs,
    )
