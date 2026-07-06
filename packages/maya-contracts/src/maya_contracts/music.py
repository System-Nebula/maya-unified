"""Music play resolve contracts — shared by Homepage and Discord."""

from __future__ import annotations

from typing import Literal, Optional

from maya_contracts.common import StrictModel


class PlayResolveRequest(StrictModel):
    """Free-text play query from a launcher (Homepage `/play`, Discord `/play`)."""

    query: str
    zone: str = "default"


MatchedVia = Literal[
    "demo_catalog",
    "exact",
    "fuzzy",
    "crate",
    "ontology",
    "url",
]


class VideoRef(StrictModel):
    """A candidate playable video, typically harvested from a Discogs master.

    The RadioPlayer cycles through these in order, using the YouTube IFrame
    API ``onError`` to skip embed-disabled videos before falling back to
    ``watch_url``.
    """

    youtube_id: str
    title: Optional[str] = None
    duration_seconds: Optional[float] = None
    embed_url: str
    watch_url: str
    source: str = "discogs"


class DiscogsRef(StrictModel):
    """Pointer back into the Discogs property graph for a resolved track."""

    master_id: Optional[int] = None
    release_id: Optional[int] = None
    url: Optional[str] = None
    year: Optional[int] = None


class SourceRefModel(StrictModel):
    """One external id in one source schema (``wd``/``yt``/``discogs``/…).

    Wire-format twin of ``maya_graph.music.primitives.SourceRef`` — no source
    schema is privileged; wikidata QIDs are just ``schema="wd"`` refs.
    """

    schema_id: str
    external_id: str
    url: Optional[str] = None
    confidence: float = 1.0


class OntologyRef(StrictModel):
    """Pointer back into the music ontology for a resolved track."""

    work_key: Optional[str] = None  # canonical_work domain_id ("wd:Q…" | "fp:…")
    work_node_id: Optional[str] = None
    recording_node_id: Optional[str] = None
    confidence: Optional[float] = None


class TrackMetadata(StrictModel):
    """Normalized lookup result from the music ontology (no playback URLs
    required — identity + cross-source refs for the agent/dashboard)."""

    title: str
    artist: Optional[str] = None
    work_key: Optional[str] = None
    aliases: list[str] = []
    source_refs: list[SourceRefModel] = []
    confidence: float = 0.0
    matched_via: MatchedVia = "ontology"


class TrackInfo(StrictModel):
    """A resolved playable track. Public-safe metadata only."""

    track_id: str
    title: str
    artist: str
    album: Optional[str] = None
    duration_seconds: Optional[float] = None
    preview_url: Optional[str] = None
    artwork_url: Optional[str] = None
    # Optional embeddable stream (YouTube embed URL, public CC stream, etc.).
    # The Homepage RadioPlayer prefers `stream_url` over `preview_url` when set
    # and renders an <iframe> for YouTube hosts.
    stream_url: Optional[str] = None
    # Optional canonical "open in source" URL. Always populated for YouTube
    # tracks so the UI can fall back to an external link when the uploader
    # has disabled in-player embedding (YouTube IFrame API error 150 / 101).
    watch_url: Optional[str] = None
    # Candidate videos harvested from ontology enrichment (Discogs master ->
    # videos[]). Player cycles through them on embed-error 150/101.
    videos: list[VideoRef] = []
    # Pointer back into the ontology graph (Discogs master/release pair).
    discogs: Optional[DiscogsRef] = None
    # Pointer into the music ontology (canonical work/recording), when the
    # resolver matched via the graph tier.
    ontology: Optional[OntologyRef] = None
    # Cross-source identity refs (schema-prefixed; wikidata is one of many).
    source_refs: list[SourceRefModel] = []


class PlayResolveResponse(StrictModel):
    """Resolver result — caller spawns a player widget around this payload."""

    matched_via: MatchedVia
    query: str
    zone: str
    tracks: list[TrackInfo]
    explanation: Optional[str] = None
