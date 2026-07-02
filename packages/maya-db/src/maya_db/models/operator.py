"""Local dashboard operator accounts.

Separate from ``platform_users`` (invite-code public platform).
These are internal users who operate the Maya Unified dashboard.
No email / OAuth / invite codes — username + argon2 password only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from maya_db.base import Base, TimestampMixin, UUIDPrimaryKey


class OperatorUser(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "operator_users"

    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="operator")
    avatar_color: Mapped[str] = mapped_column(String(16), nullable=False, server_default="#0a84ff")
    last_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
