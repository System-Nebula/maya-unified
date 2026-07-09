"""Merge DJ set entries across YouTube, 1001tracklists, and Apple Music."""

from __future__ import annotations

import re
from dataclasses import replace

from maya_contracts import SourceRefModel
from rapidfuzz import fuzz

from services.music.url_handler import PLATFORM_1001TL, PLATFORM_APPLE, PLATFORM_YOUTUBE, ResolvedSet, SetEntry

_TIMESTAMP_TOLERANCE = 15


def _norm(text: str | None) -> str:
    value = (text or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _title_score(a: SetEntry, b: SetEntry) -> float:
    left = _norm(f"{a.artist or ''} {a.title or a.label}")
    right = _norm(f"{b.artist or ''} {b.title or b.label}")
    if not left or not right:
        return 0.0
    return fuzz.token_set_ratio(left, right) / 100.0


def _timestamp_score(a: SetEntry, b: SetEntry) -> float:
    if a.start_seconds is None or b.start_seconds is None:
        return 0.0
    delta = abs(a.start_seconds - b.start_seconds)
    if delta <= _TIMESTAMP_TOLERANCE:
        return 1.0 - (delta / _TIMESTAMP_TOLERANCE) * 0.5
    return 0.0


def _position_score(a: SetEntry, b: SetEntry) -> float:
    return 1.0 if a.position == b.position else 0.0


def _merge_entry(primary: SetEntry, other: SetEntry) -> SetEntry:
    refs: list[SourceRefModel] = list(primary.source_refs)
    seen = {(r.schema_id, r.external_id) for r in refs}
    for ref in other.source_refs:
        key = (ref.schema_id, ref.external_id)
        if key not in seen:
            seen.add(key)
            refs.append(ref)

    end_seconds = primary.end_seconds if primary.end_seconds is not None else other.end_seconds
    start_seconds = primary.start_seconds or other.start_seconds
    artist = primary.artist or other.artist
    title = primary.title or other.title
    attrs = {**other.attrs, **primary.attrs}

    return replace(
        primary,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        artist=artist,
        title=title,
        source_refs=refs,
        attrs=attrs,
    )


def _pick_primary(*sets: ResolvedSet) -> ResolvedSet:
    for preferred in (PLATFORM_YOUTUBE, PLATFORM_1001TL, PLATFORM_APPLE):
        for item in sets:
            if item.container_schema == preferred:
                return item
    return sets[0]


def correlate_sets(primary: ResolvedSet, *others: ResolvedSet) -> ResolvedSet:
    """Merge entries across sources into one unified set."""
    if not others:
        return primary

    all_sets = (primary, *others)
    base = _pick_primary(*all_sets)
    pool: list[SetEntry] = []
    for item in all_sets:
        if item.set_key == base.set_key:
            continue
        pool.extend(item.entries)

    merged: list[SetEntry] = []
    used: set[int] = set()

    for entry in sorted(base.entries, key=lambda e: e.position):
        best_idx: int | None = None
        best_score = 0.0
        for idx, candidate in enumerate(pool):
            if idx in used:
                continue
            score = (
                _title_score(entry, candidate) * 0.55
                + _timestamp_score(entry, candidate) * 0.30
                + _position_score(entry, candidate) * 0.15
            )
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx is not None and best_score >= 0.45:
            used.add(best_idx)
            merged.append(_merge_entry(entry, pool[best_idx]))
        else:
            merged.append(entry)

    linked: list[SourceRefModel] = list(base.linked_sets)
    seen_links = {(r.schema_id, r.external_id) for r in linked}
    for item in all_sets:
        key = (item.container_schema, item.set_key.split(":", 1)[-1])
        ref = SourceRefModel(
            schema_id=item.container_schema,
            external_id=key[1],
            url=item.container_url,
            confidence=0.95,
        )
        link_key = (ref.schema_id, ref.external_id)
        if link_key not in seen_links:
            seen_links.add(link_key)
            linked.append(ref)

    for i, entry in enumerate(merged, start=1):
        entry.position = i

    return replace(
        base,
        entries=merged,
        linked_sets=linked,
        attrs={**base.attrs, "correlated": True, "source_count": len(all_sets)},
    )
