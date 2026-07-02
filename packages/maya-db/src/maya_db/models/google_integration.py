"""Google OAuth integration metadata (tokens stored outside Postgres)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from maya_db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKey


class OperatorGoogleIdentity(Base, UUIDPrimaryKey, TimestampMixin):
    """Links a dashboard operator to a Google account for sign-in."""

    __tablename__ = "operator_google_identities"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operator_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    google_sub: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class GoogleConnection(Base, UUIDPrimaryKey, TimestampMixin):
    """Connected Google integration for an operator (refresh token on disk/OpenBao)."""

    __tablename__ = "google_connections"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operator_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    google_sub: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    scopes: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class OAuthPkceState(Base, UUIDPrimaryKey):
    """Short-lived PKCE state for Google OAuth login and connect flows."""

    __tablename__ = "oauth_pkce_states"

    state: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    verifier: Mapped[str] = mapped_column(String(256), nullable=False)
    flow: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_scopes: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("operator_users.id", ondelete="CASCADE"),
        nullable=True,
    )
    session_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
