"""Music acquisition query contracts — search Soulseek, acquire to SeaweedFS, reference from ontology graph."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from maya_contracts.common import StrictModel


class QualityTier(str, Enum):
    """Canonical quality tiers for audio files, ordered best→worst."""

    LOSSLESS_24BIT = "24bit_lossless"
    LOSSLESS = "lossless"
    LOSSLESS_CD = "lossless_cd"
    HIGH = "320"
    STANDARD = "v0"
    AAC_256 = "aac_256"
    LOW = "low"
    UNKNOWN = "unknown"


def infer_quality_tier(ext: str, filename: str = "") -> QualityTier | None:
    """Guess quality tier from extension and filename hints.

    Looks for 24bit, 96k, vinyl, cd, 320, v0, aac etc. in the filename
    and maps known extensions.
    """
    lower = filename.lower()
    ext_lower = ext.lower().lstrip(".")

    if "24bit" in lower or "24-96" in lower or "24/96" in lower:
        return QualityTier.LOSSLESS_24BIT
    if ext_lower == "flac":
        if "vinyl" in lower or "web" in lower:
            return QualityTier.LOSSLESS_24BIT
        return QualityTier.LOSSLESS
    if ext_lower == "wav":
        return QualityTier.LOSSLESS
    if ext_lower in ("aiff", "aif"):
        return QualityTier.LOSSLESS
    if ext_lower == "m4a":
        if "256" in lower or "aac" in lower:
            return QualityTier.AAC_256
        return QualityTier.HIGH
    if ext_lower == "mp3":
        if "320" in lower or "cbr" in lower:
            return QualityTier.HIGH
        if "v0" in lower or "vbr" in lower:
            return QualityTier.STANDARD
        return QualityTier.STANDARD
    if ext_lower in ("ogg", "opus"):
        return QualityTier.HIGH
    return None


def compute_quality_score(quality_tier: QualityTier | None, has_free_slot: bool, queue_length: int) -> float:
    """Rank a hit from 0-100. Higher is better.

    Base score from quality tier, then penalise locked/queued.
    """
    tier_scores = {
        QualityTier.LOSSLESS_24BIT: 90,
        QualityTier.LOSSLESS: 80,
        QualityTier.LOSSLESS_CD: 75,
        QualityTier.HIGH: 55,
        QualityTier.STANDARD: 40,
        QualityTier.AAC_256: 35,
        QualityTier.LOW: 20,
        QualityTier.UNKNOWN: 10,
    }
    base = tier_scores.get(quality_tier or QualityTier.UNKNOWN, 10)
    slot_bonus = 10 if has_free_slot else 0
    queue_penalty = min(queue_length * 2, 20)
    return max(0.0, float(base + slot_bonus - queue_penalty))


class FormatInfo(StrictModel):
    """Detected or declared encoding parameters."""

    extension: str
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    bit_depth: Optional[int] = None
    quality_tier: QualityTier = QualityTier.UNKNOWN


class SearchHit(StrictModel):
    """A single file returned by a Soulseek search."""

    username: str
    filename: str  # Windows-style path from slskd
    size: int  # bytes
    extension: str
    is_locked: bool = False
    has_free_slot: bool = False
    queue_length: int = 0
    upload_speed: Optional[int] = None

    # Computed fields (set by adapter, not user-supplied)
    quality_tier: QualityTier = QualityTier.UNKNOWN
    quality_score: float = 0.0

    # Parsed filename hints (best-effort)
    artist_hint: Optional[str] = None
    album_hint: Optional[str] = None
    title_hint: Optional[str] = None


class SearchQuery(StrictModel):
    """Structured query composed by the query builder."""

    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    label: Optional[str] = None
    catalog_number: Optional[str] = None
    exact_phrase: bool = True
    format_filter: Optional[QualityTier] = None
    min_size: Optional[int] = None  # minimum file size in bytes
    max_size: Optional[int] = None
    user: Optional[str] = None  # restrict to a specific Soulseek user
    max_results: int = 50

    def to_slskd_text(self) -> str:
        """Compose a flat search string from structured fields."""
        parts = []
        if self.artist:
            parts.append(self.artist)
        if self.album:
            parts.append(self.album)
        if self.title:
            parts.append(self.title)
        if self.label:
            parts.append(self.label)
        if self.catalog_number:
            parts.append(self.catalog_number)
        query = " ".join(parts)
        if self.exact_phrase:
            query = f'"{query}"'
        return query


class SearchResult(StrictModel):
    """Typed result from a slskd search."""

    query: SearchQuery
    hits: tuple[SearchHit, ...]
    total_hits: int
    search_id: str
    elapsed_seconds: float

    def best(self) -> SearchHit | None:
        """Return the highest-scoring hit, or None."""
        if not self.hits:
            return None
        return max(self.hits, key=lambda h: h.quality_score)


class AcquisitionStatus(str, Enum):
    """Lifecycle of a music download from request to graph reference."""

    PENDING = "pending"
    ENQUEUED = "enqueued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    UPLOADED = "uploaded"
    GRAPHED = "graphed"
    FAILED = "failed"


class AcquisitionRequest(StrictModel):
    """Request to download a specific SearchHit and store it."""

    hit: SearchHit
    artist_slug: Optional[str] = None
    album_slug: Optional[str] = None
    track_number: Optional[int] = None
    title_override: Optional[str] = None
    s3_bucket: str = "music"
    s3_prefix: Optional[str] = None  # override auto-generated S3 key
    import_to_beets: bool = True

    def build_s3_key(self) -> str:
        """Generate a canonical S3 key from the hit + structured metadata.

        Pattern: {artist_slug}/{album_slug}/{nn}-{title_slug}.{ext}
        Falls back to a hash-based key if slugs are missing.
        """
        if self.s3_prefix:
            return self.s3_prefix

        artist = self.artist_slug or "unknown"
        album = self.album_slug or "unknown"
        track = self.title_override or ""
        if not track:
            # Use PureWindowsPath for Soulseek paths
            from pathlib import PureWindowsPath
            track = PureWindowsPath(self.hit.filename).stem
        num = f"{self.track_number:02d}-" if self.track_number is not None else ""
        ext = self.hit.extension.lower().lstrip(".")
        return f"{artist}/{album}/{num}{track}.{ext}"


class AcquisitionResult(StrictModel):
    """Result of an acquisition attempt."""

    request: AcquisitionRequest
    status: AcquisitionStatus
    slskd_transfer_id: Optional[str] = None
    s3_key: Optional[str] = None
    s3_url: Optional[str] = None
    ontology_node_id: Optional[str] = None
    ontology_node_slug: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = datetime.now()


class SavedQuery(StrictModel):
    """A reusable search query persisted in the ontology graph."""

    slug: str
    label: str
    query: SearchQuery
    last_result_hash: Optional[str] = None
    best_result_slug: Optional[str] = None
    times_run: int = 0
    last_run_at: Optional[datetime] = None
