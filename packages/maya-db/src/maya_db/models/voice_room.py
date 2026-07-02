"""Public multi-user voice rooms."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from maya_db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKey


class VoiceRoom(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "voice_rooms"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    owner_operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, server_default="private")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    max_participants: Mapped[int] = mapped_column(Integer, nullable=False, server_default="20")
    personality_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, server_default="{}")
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, server_default="{}")

    members: Mapped[list["VoiceRoomMember"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    messages: Mapped[list["VoiceRoomMessage"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    queue_entries: Mapped[list["VoiceRoomVoiceQueue"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class VoiceRoomMember(Base, UUIDPrimaryKey):
    __tablename__ = "voice_room_members"
    __table_args__ = (
        UniqueConstraint("room_id", "operator_id", name="uq_voice_room_members_room_operator"),
    )

    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("voice_rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_users.id", ondelete="SET NULL"), nullable=True
    )
    guest_token_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="member")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    room: Mapped["VoiceRoom"] = relationship(back_populates="members")


class VoiceRoomMessage(Base):
    __tablename__ = "voice_room_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("voice_rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("voice_room_members.id", ondelete="SET NULL"), nullable=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    room: Mapped["VoiceRoom"] = relationship(back_populates="messages")


class VoiceRoomVoiceQueue(Base, UUIDPrimaryKey):
    __tablename__ = "voice_room_voice_queue"

    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("voice_rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("voice_room_members.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="waiting")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    room: Mapped["VoiceRoom"] = relationship(back_populates="queue_entries")
