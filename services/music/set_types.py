"""Shared DJ set datatypes for music URL handling and graph ingest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maya_contracts import SourceRefModel

PLATFORM_YOUTUBE = "yt"
PLATFORM_1001TL = "1001tl"
PLATFORM_APPLE = "apple_music"


@dataclass
class SetEntry:
    position: int
    start_seconds: int
    end_seconds: int | None
    label: str
    artist: str | None
    title: str | None
    work_key: str | None = None
    play_url: str | None = None
    play_mode: str = "seek"
    source_refs: list[SourceRefModel] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedSet:
    set_key: str
    title: str
    container_url: str
    container_schema: str
    entries: list[SetEntry]
    linked_sets: list[SourceRefModel] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)
