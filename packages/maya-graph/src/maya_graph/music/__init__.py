"""Music ontology — normalized primitives + parameterized query broker.

Layout:
- ``primitives``: the normalized primitive data types every tier speaks
  (SourceRef, CanonicalWork, Recording, WorkQuery, ...).
- ``broker``: MusicQueryBroker — single entry point that normalizes a
  parameterized query and brokers it across the property graph and
  registered source schemas.
- ``schemas``: pluggable source-schema adapters (Wikidata, MusicBrainz,
  Discogs, Apple Music / iTunes).
- ``normalize`` / ``catalog``: parse messy strings and map them onto those
  schemas so graph nodes store canonical artist/title plus external ids.
"""

from maya_graph.music.broker import MusicQueryBroker
from maya_graph.music.primitives import (
    ArtistRef,
    CanonicalWork,
    Recording,
    RecordingQuery,
    ResolutionEvent,
    SourceRef,
    WorkCandidate,
    WorkQuery,
    canonical_fingerprint,
    work_key_from_fingerprint,
)
from maya_graph.music.catalog import map_identity
from maya_graph.music.normalize import ParsedTrack, parse_share_path
from maya_graph.music.schemas.base import SourceSchema
from maya_graph.music.schemas import default_catalog_schemas

__all__ = [
    "ArtistRef",
    "CanonicalWork",
    "MusicQueryBroker",
    "Recording",
    "RecordingQuery",
    "ResolutionEvent",
    "SourceRef",
    "SourceSchema",
    "WorkCandidate",
    "WorkQuery",
    "ParsedTrack",
    "default_catalog_schemas",
    "map_identity",
    "parse_share_path",
    "canonical_fingerprint",
    "work_key_from_fingerprint",
]
