"""Feed intel contracts: release diff analysis and YouTube description extraction."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from maya_contracts.common import StrictModel


class IntelItemKind(str, Enum):
    REPO = "repo"
    PAPER = "paper"
    PRODUCT = "product"
    DEMO = "demo"
    MODEL = "model"
    UNKNOWN = "unknown"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class AnalysisKind(str, Enum):
    RELEASE_DIFF = "release_diff"
    VIDEO_INTEL = "video_intel"


class FileChange(StrictModel):
    filename: str
    status: str
    additions: int = 0
    deletions: int = 0
    patch: Optional[str] = None


class AnalysisSummary(StrictModel):
    summary: str
    breaking_changes: list[str] = []
    affected_subsystems: list[str] = []
    doc_sections: list[str] = []


class ReleaseAnalysis(StrictModel):
    id: Optional[str] = None
    repo: str
    from_tag: Optional[str] = None
    to_tag: str
    release_url: str
    release_notes: Optional[str] = None
    file_changes: list[FileChange] = []
    analysis: Optional[AnalysisSummary] = None
    generated_at: datetime


class Chapter(StrictModel):
    timestamp: str
    label: str
    timestamp_seconds: Optional[int] = None


class IntelItem(StrictModel):
    id: Optional[str] = None
    label: str
    url: str
    canonical_url: str
    kind: IntelItemKind = IntelItemKind.UNKNOWN
    timestamp_seconds: Optional[int] = None
    metadata: dict[str, Any] = {}
    first_seen_at: Optional[datetime] = None


class VideoIntel(StrictModel):
    video_id: str
    channel_id: str
    title: str
    chapters: list[Chapter] = []
    items: list[IntelItem] = []
    generated_at: datetime


class TrendCluster(StrictModel):
    canonical_url: str
    label: str
    kind: IntelItemKind
    item_count: int
    channel_count: int
    channels: list[str] = []
    first_seen: datetime
    last_seen: datetime


class AnalysisConfig(StrictModel):
    kind: str  # github_releases | youtube_intel
    auto_analyze: bool = True
    ignore_patterns: list[str] = []
    llm_enabled: bool = True
