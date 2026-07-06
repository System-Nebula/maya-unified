"""Source-schema protocol — external knowledge schemas the broker builds off.

Wikidata is one schema; Discogs, SoundCloud, and Beatport are designed peers.
Adapters normalize their source's shapes into the music primitives and must
be best-effort: return empty/None on any failure, never raise into the
broker's hot path.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from maya_graph.music.primitives import CanonicalWork, Recording, SourceRef, WorkQuery


@runtime_checkable
class SourceSchema(Protocol):
    schema_id: str  # "wd" | "discogs" | "soundcloud" | ...

    async def search_work(self, query: WorkQuery) -> list[CanonicalWork]:
        """Best-effort canonical-work search. Empty list on miss or failure."""
        ...

    async def fetch_recording(self, ref: SourceRef) -> Recording | None:
        """Optional: resolve a playable recording for a ref this schema owns."""
        ...

    async def fetch_recordings(self, work: CanonicalWork) -> list[Recording]:
        """Optional: all playable recordings linked to a canonical work."""
        ...
