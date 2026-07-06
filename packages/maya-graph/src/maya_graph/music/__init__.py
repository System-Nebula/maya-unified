"""Music ontology — normalized primitives + parameterized query broker.

Layout:
- ``primitives``: the normalized primitive data types every tier speaks
  (SourceRef, CanonicalWork, Recording, WorkQuery, ...).
- ``broker``: MusicQueryBroker — single entry point that normalizes a
  parameterized query and brokers it across the property graph and
  registered source schemas.
- ``schemas``: pluggable source-schema adapters. Wikidata is one schema we
  build off; Discogs/SoundCloud/Beatport are designed peers.
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
from maya_graph.music.schemas.base import SourceSchema

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
    "canonical_fingerprint",
    "work_key_from_fingerprint",
]
