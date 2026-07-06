"""Image director session persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from maya_db.base import Base, JSONType


class ImageSessionTable(Base):
    __tablename__ = "image_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    operator_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    discord_user_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    discord_channel_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    active_version_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_image_sessions_operator_updated", "operator_id", "updated_at"),
        Index("ix_image_sessions_discord_channel", "discord_user_id", "discord_channel_id"),
    )
