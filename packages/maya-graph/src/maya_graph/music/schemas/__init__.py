"""Pluggable source-schema adapters for the music query broker."""

from maya_graph.music.schemas.base import SourceSchema
from maya_graph.music.schemas.discogs import DiscogsSchema
from maya_graph.music.schemas.itunes import ItunesSchema
from maya_graph.music.schemas.musicbrainz import MusicBrainzSchema
from maya_graph.music.schemas.wikidata import WikidataSchema


def default_catalog_schemas() -> list[SourceSchema]:
    """Wikidata first (QIDs + harvested catalog ids), then MB / Discogs / Apple."""
    return [WikidataSchema(), MusicBrainzSchema(), DiscogsSchema(), ItunesSchema()]


__all__ = [
    "DiscogsSchema",
    "ItunesSchema",
    "MusicBrainzSchema",
    "SourceSchema",
    "WikidataSchema",
    "default_catalog_schemas",
]
