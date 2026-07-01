"""Arena database models — UUID PKs with cross-modal image/TTS support."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from maya_db.base import Base, TimestampMixin, UUIDPrimaryKey


class Candidate(Base, UUIDPrimaryKey, TimestampMixin):
    """An arena candidate (TTS voice / image model / persona)."""

    __tablename__ = "arena_candidates"

    model_release_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("model_releases.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    modality: Mapped[str] = mapped_column(String(16), default="tts", nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    voice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    variant_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    settings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    rating: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    rating_deviation: Mapped[float] = mapped_column(Float, default=350.0, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    draws: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_battles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    model_key = synonym("voice_id")

    model_release: Mapped[Optional["ModelRelease"]] = relationship(
        "ModelRelease", back_populates="candidates"
    )
    battles_a: Mapped[list["Battle"]] = relationship(
        "Battle", foreign_keys="Battle.candidate_a_id", back_populates="candidate_a"
    )
    battles_b: Mapped[list["Battle"]] = relationship(
        "Battle", foreign_keys="Battle.candidate_b_id", back_populates="candidate_b"
    )

    __table_args__ = (
        Index("ix_candidates_modality_rating", "modality", "rating"),
        Index("ix_candidates_provider_model", "provider", "voice_id"),
        Index("ix_candidates_modality_active", "modality", "is_active", "rating"),
    )


class Battle(Base, UUIDPrimaryKey, TimestampMixin):
    """An arena battle between two candidates."""

    __tablename__ = "arena_battles"

    modality: Mapped[str] = mapped_column(String(16), default="tts", nullable=False, index=True)
    candidate_a_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("arena_candidates.id"), nullable=False
    )
    candidate_b_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("arena_candidates.id"), nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    winner_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)

    votes_a: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    votes_b: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    votes_tie: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_votes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    candidate_a: Mapped["Candidate"] = relationship(
        "Candidate", foreign_keys=[candidate_a_id], back_populates="battles_a"
    )
    candidate_b: Mapped["Candidate"] = relationship(
        "Candidate", foreign_keys=[candidate_b_id], back_populates="battles_b"
    )

    __table_args__ = (
        Index("ix_battles_modality_created", "modality", "created_at"),
        Index("ix_battles_candidates", "candidate_a_id", "candidate_b_id"),
    )

    @property
    def is_complete(self) -> bool:
        return self.status == "completed"


class ArenaArtifact(Base, UUIDPrimaryKey):
    """Output artifact produced by one candidate in a battle."""

    __tablename__ = "arena_artifacts"

    battle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("arena_battles.id"), nullable=False, index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("arena_candidates.id"), nullable=False, index=True
    )
    slot: Mapped[str] = mapped_column(String(8), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_artifacts_battle_slot", "battle_id", "slot"),)


class ArenaVote(Base, UUIDPrimaryKey):
    """Explicit vote or passive reaction signal on a battle."""

    __tablename__ = "arena_votes"

    battle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("arena_battles.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    choice: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(32), default="explicit_vote", nullable=False)
    reaction: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_votes_battle_user_signal",
            "battle_id",
            "user_id",
            "signal_type",
            unique=True,
        ),
    )


class ArenaSession(Base, UUIDPrimaryKey):
    """Maps an active battle to a Discord/UI session."""

    __tablename__ = "arena_sessions"

    battle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("arena_battles.id"), nullable=False, index=True
    )
    started_by: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    guild_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


# Aliases used by the image arena service (ported from private lib.db.arena).
ArenaCandidate = Candidate
ArenaBattle = Battle
