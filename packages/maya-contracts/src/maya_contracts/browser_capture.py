"""Browser capture API contracts and outbox graph events."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from maya_contracts.common import StrictModel

SCHEMA_VERSION = 1

AssetKind = Literal[
    "html",
    "reader_html",
    "screenshot",
    "dom_json",
    "pdf",
    "audio",
    "video",
    "mhtml",
    "favicon",
]

CaptureType = Literal[
    "article",
    "image",
    "video",
    "product",
    "repo",
    "paper",
    "tweet",
    "recipe",
    "tracklist",
    "generic",
]


class CaptureAsset(BaseModel):
    """A single blob attached to a capture."""

    model_config = ConfigDict(strict=True, extra="forbid")

    kind: AssetKind
    mime_type: str
    data_b64: str = Field(..., description="Base64-encoded blob content")

    @field_validator("data_b64")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("data_b64 must not be empty")
        return v


class CaptureEvent(BaseModel):
    """Payload sent by the extension on browser.capture."""

    model_config = ConfigDict(strict=True, extra="forbid")

    event: Literal["browser.capture"] = "browser.capture"
    capture_type: CaptureType
    url: str
    title: str | None = None
    selection: str | None = None
    reader_text: str | None = None
    favicon_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    assets: list[CaptureAsset] = Field(default_factory=list)
    client_captured_at: float = Field(default_factory=time.time)


class StoredAssetDescriptor(StrictModel):
    kind: str
    key: str
    mime_type: str
    size_bytes: int
    sha256: str


class CaptureManifest(StrictModel):
    """Response returned to the extension after capture."""

    capture_id: str
    content_hash: str
    duplicate: bool
    stored_assets: list[StoredAssetDescriptor]
    queued_at: float


class BrowserCaptureGraphEvent(StrictModel):
    """Frozen outbox payload — future maya-enrichd consumer contract."""

    schema_version: int = SCHEMA_VERSION
    kind: Literal["page_captured"] = "page_captured"
    capture_id: str
    content_hash: str
    capture_type: str
    url: str
    title: str = ""
    reader_text: str = ""
    selection: str = ""
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    operator_id: str | None = None
