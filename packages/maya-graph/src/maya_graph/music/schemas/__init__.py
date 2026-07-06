"""Pluggable source-schema adapters for the music query broker."""

from maya_graph.music.schemas.base import SourceSchema
from maya_graph.music.schemas.wikidata import WikidataSchema

__all__ = ["SourceSchema", "WikidataSchema"]
