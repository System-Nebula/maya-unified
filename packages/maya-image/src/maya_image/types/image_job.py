"""Normalized image job contracts for Maya."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Any

from pydantic import BaseModel, Field


class ImageJobStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageMode(str, Enum):
    GENERATE = "generate"
    EDIT = "edit"
    ARENA = "arena"
    REFINE = "refine"
    DIRECTOR = "director"


class ImageReference(BaseModel):
    source_url: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    local_path: Optional[str] = None


class ImageOutput(BaseModel):
    url: str
    local_path: Optional[str] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class ImageJobInput(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    mode: ImageMode = ImageMode.GENERATE
    references: list[ImageReference] = Field(default_factory=list)
    mask_url: Optional[str] = None
    size: str = "1024x1024"
    quality: str = "high"
    user_id: Optional[str] = None
    guild_id: Optional[str] = None
    channel_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageJobOutput(BaseModel):
    provider: str
    model: str
    outputs: list[ImageOutput] = Field(default_factory=list)
    revised_prompt: Optional[str] = None
    latency_ms: Optional[int] = None
    raw_response: dict[str, Any] = Field(default_factory=dict)


class ImageJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider_key: str
    provider_job_id: Optional[str] = None
    status: ImageJobStatus = ImageJobStatus.PENDING
    input: ImageJobInput
    output: Optional[ImageJobOutput] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ImageJobSubmission(BaseModel):
    job_id: str
    status: ImageJobStatus

