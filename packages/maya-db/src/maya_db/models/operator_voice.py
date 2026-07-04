"""Per-operator voice workspace: settings, personalities, conversation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from maya_db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKey


class OperatorVoiceSettings(Base, TimestampMixin):
    __tablename__ = "operator_voice_settings"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operator_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, server_default="{}")


class OperatorPersonalities(Base, TimestampMixin):
    __tablename__ = "operator_personalities"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operator_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    active_slug: Mapped[str] = mapped_column(String(128), nullable=False, server_default="default")
    personalities: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, server_default="{}")


class OperatorConversationSession(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "operator_conversation_sessions"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operator_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, nullable=False, server_default="{}")

    messages: Mapped[list["OperatorConversationMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class OperatorConversationMessage(Base):
    __tablename__ = "operator_conversation_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operator_conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("operator_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    corr_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    completion_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    session: Mapped["OperatorConversationSession"] = relationship(back_populates="messages")
