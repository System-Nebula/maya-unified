"""Shared base types and response envelopes."""

from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class StrictModel(BaseModel):
    """Immutable, strictly-typed Pydantic base for all API contracts."""

    model_config = ConfigDict(strict=True, frozen=True)


class ErrorResponse(StrictModel):
    detail: str
    code: str | None = None


class PaginatedResponse(StrictModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class MediaSourceStatus(str, Enum):
    """Lifecycle state of a media asset relative to its origin source."""

    ACTIVE = "active"
    MISSING = "missing"
    DELETED_FROM_SOURCE = "deleted_from_source"
