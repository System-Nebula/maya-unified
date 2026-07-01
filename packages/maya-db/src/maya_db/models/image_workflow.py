"""Postgres registry of runnable image generation workflows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from maya_db.base import Base, JSONType


class ImageWorkflowRow(Base):
    __tablename__ = "image_workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ui_schema: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    comfy_graph: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    elo_score: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_arena_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    arena_competitor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("image_workflows.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
