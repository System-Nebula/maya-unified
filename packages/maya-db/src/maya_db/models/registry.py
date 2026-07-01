"""Registry database models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from maya_db.base import Base, TimestampMixin, UUIDPrimaryKey


class ModelRelease(Base, UUIDPrimaryKey, TimestampMixin):
    """Canonical model release record."""

    __tablename__ = "model_releases"

    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    capability_family: Mapped[str] = mapped_column(String(32), nullable=False)
    modality_in: Mapped[list[str]] = mapped_column(JSON, default=list)
    modality_out: Mapped[list[str]] = mapped_column(JSON, default=list)
    base_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    quantization: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    runtime: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    eval_status: Mapped[str] = mapped_column(
        String(32), default="discovered", nullable=False, index=True
    )
    publisher_claims: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    eval_runs: Mapped[list["EvalRun"]] = relationship(
        "EvalRun", back_populates="model_release"
    )
    candidates: Mapped[list["Candidate"]] = relationship(
        "Candidate", back_populates="model_release"
    )


class EvalRun(Base, UUIDPrimaryKey, TimestampMixin):
    """Single evaluation run for a model release."""

    __tablename__ = "eval_runs"

    model_release_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_releases.id"), nullable=False, index=True
    )
    eval_suite: Mapped[str] = mapped_column(String(128), nullable=False)
    eval_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", nullable=False, index=True
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    model_release: Mapped["ModelRelease"] = relationship(
        "ModelRelease", back_populates="eval_runs"
    )
