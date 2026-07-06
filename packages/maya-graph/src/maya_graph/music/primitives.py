"""Normalized primitive data types for the music domain.

Every tier — graph storage, source schemas, the query broker, and platform
services — normalizes into these types. Identity is schema-prefixed
(``wd:Q…``, ``yt:…``, ``discogs:…``, ``fp:…``) so no single external source
is privileged: Wikidata is one schema we build off, not a column name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maya_graph.projector import normalize_key

DOMAIN = "music"

# --- node types (ontology_node.node_type; domain_id convention noted) ---
NODE_CANONICAL_WORK = "canonical_work"  # domain_id = work key ("wd:Q…" | "fp:…")
NODE_RECORDING = "recording"  # domain_id = SourceRef.domain_key() ("yt:…", "bandcamp:…")
NODE_ARTIST = "artist"  # domain_id = slug (artist_bridge.slugify)
NODE_RELEASE = "release"

# --- edge types ---
EDGE_HAS_RECORDING = "has_recording"  # canonical_work -> recording
EDGE_PERFORMED_BY = "performed_by"  # work/recording -> artist
EDGE_SAME_AS = "same_as"  # cross-schema identity (recording <-> recording)
EDGE_ALIAS_OF = "alias_of"
EDGE_DERIVED_FROM = "derived_from"  # remix/edit -> original work
EDGE_SIMILAR_TO = "similar_to"
EDGE_IN_GENRE = "in_genre"  # work/artist -> shared genre facet
EDGE_APPEARS_ON = "appears_on"  # recording -> release

# --- dimensions (subset of the private ontology vocabulary music uses) ---
DIM_SEMANTIC = "semantic"
DIM_ACOUSTIC = "acoustic"
DIM_SOCIAL = "social"
DIM_TEMPORAL = "temporal"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Cross-schema identity atom: one external id in one source schema."""

    schema: str  # "wd" | "yt" | "discogs" | "bandcamp" | "soundcloud" | "slskd" | ...
    external_id: str
    url: str | None = None

    def domain_key(self) -> str:
        """Graph ``domain_id`` encoding of this ref, e.g. ``yt:dQw4w9WgXcQ``."""
        return f"{self.schema}:{self.external_id}"

    @classmethod
    def from_domain_key(cls, key: str, *, url: str | None = None) -> "SourceRef":
        schema, _, external_id = key.partition(":")
        return cls(schema=schema, external_id=external_id, url=url)


@dataclass(frozen=True, slots=True)
class ArtistRef:
    slug: str  # artist_bridge.slugify(name)
    name: str


@dataclass(frozen=True, slots=True)
class CanonicalWork:
    """Canonical song/work identity — the thing recordings are instances of."""

    key: str  # graph domain_id: "wd:Q…" (anchored) or "fp:<fingerprint>" (internal)
    label: str
    aliases: tuple[str, ...] = ()
    anchors: tuple[SourceRef, ...] = ()  # external ids asserting this identity
    artists: tuple[ArtistRef, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Recording:
    """A playable instance of a work in one source schema."""

    source: SourceRef
    title: str | None = None
    duration_seconds: int | None = None
    webpage_url: str | None = None
    stream_url: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkQuery:
    """Parameterized work lookup — the broker's input surface."""

    text: str | None = None
    artist: str | None = None
    source_ref: SourceRef | None = None
    fingerprint: str | None = None
    limit: int = 5


@dataclass(frozen=True, slots=True)
class RecordingQuery:
    """Parameterized recording lookup: by owning work key or by source ref."""

    work_key: str | None = None
    source_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class WorkCandidate:
    """A scored work match. ``node_id`` is None for schema results whose
    write-through has not landed in the graph yet."""

    work: CanonicalWork
    confidence: float
    node_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolutionEvent:
    """Normalized outcome of a brokered resolution, emitted to the
    ``on_resolution`` hook so the platform layer can persist relational rows
    without maya-graph depending on maya-db."""

    work: CanonicalWork
    recordings: tuple[Recording, ...]
    source_schema: str  # schema_id that produced it ("graph" for cache hits)
    confidence: float


def canonical_fingerprint(
    artist: str,
    base_title: str,
    remix: str | None = None,
    version: str | None = None,
) -> str:
    """Stable identity fingerprint: ``artist::base-title::remix::version``.

    Reuses ``projector.normalize_key`` semantics (case/punct-insensitive).
    """
    return "::".join(
        (
            normalize_key(artist),
            normalize_key(base_title),
            normalize_key(remix) if remix else "",
            normalize_key(version) if version else "original",
        )
    )


def work_key_from_fingerprint(fingerprint: str) -> str:
    """Work key for internally-identified works with no external anchor yet."""
    return f"fp:{fingerprint}"
