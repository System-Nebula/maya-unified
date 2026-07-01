"""Image job persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from maya_db.base import Base, JSONType


class ImageJobTable(Base):
    __tablename__ = "image_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    provider_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider_job_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", index=True)

    mode: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quality: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mask_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    references: Mapped[list[Any]] = mapped_column(JSONType, default=list)

    output: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_image_jobs_status_created", "status", "created_at"),
        Index("ix_image_jobs_provider_status", "provider_key", "status"),
        Index("ix_image_jobs_user_created", "user_id", "created_at"),
    )
