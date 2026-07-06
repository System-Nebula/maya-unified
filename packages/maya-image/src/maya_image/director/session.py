"""Load and save ImageSessionState to Postgres."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from maya_db.models.image_session import ImageSessionTable
from maya_db.sync_connection import get_sync_connection
from maya_image.director.state import ImageSessionState

logger = structlog.get_logger()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(
    *,
    operator_id: str | None = None,
    discord_user_id: str | None = None,
    discord_channel_id: str | None = None,
    initial_state: ImageSessionState | None = None,
) -> tuple[str, ImageSessionState]:
    session_id = str(uuid.uuid4())
    state = initial_state or ImageSessionState()
    save_session(session_id, state, operator_id=operator_id, discord_user_id=discord_user_id, discord_channel_id=discord_channel_id)
    return session_id, state


def save_session(
    session_id: str,
    state: ImageSessionState,
    *,
    operator_id: str | None = None,
    discord_user_id: str | None = None,
    discord_channel_id: str | None = None,
) -> bool:
    try:
        conn = get_sync_connection()
        db = conn.get_session()
        try:
            row = db.get(ImageSessionTable, session_id)
            now = _now()
            payload = state.model_dump(mode="json")
            if row is None:
                row = ImageSessionTable(
                    id=session_id,
                    operator_id=operator_id,
                    discord_user_id=discord_user_id,
                    discord_channel_id=discord_channel_id,
                    active_version_id=state.current_version_id,
                    state=payload,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            else:
                row.state = payload
                row.active_version_id = state.current_version_id
                row.updated_at = now
                if operator_id:
                    row.operator_id = operator_id
                if discord_user_id:
                    row.discord_user_id = discord_user_id
                if discord_channel_id:
                    row.discord_channel_id = discord_channel_id
            db.commit()
            return True
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_session_save_failed", session_id=session_id, error=str(exc))
        return False


def load_session(session_id: str) -> ImageSessionState | None:
    try:
        conn = get_sync_connection()
        db = conn.get_session()
        try:
            row = db.get(ImageSessionTable, session_id)
            if row is None:
                return None
            return ImageSessionState.model_validate(row.state or {})
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_session_load_failed", session_id=session_id, error=str(exc))
        return None


def find_session_for_discord(
    *,
    discord_user_id: str,
    discord_channel_id: str,
    max_age_hours: int = 24,
) -> str | None:
    """Return the most recent active session for a Discord channel."""
    try:
        conn = get_sync_connection()
        db = conn.get_session()
        try:
            from sqlalchemy import select

            cutoff = _now().replace(hour=0, minute=0, second=0, microsecond=0)
            stmt = (
                select(ImageSessionTable)
                .where(ImageSessionTable.discord_user_id == discord_user_id)
                .where(ImageSessionTable.discord_channel_id == discord_channel_id)
                .where(ImageSessionTable.updated_at >= cutoff)
                .order_by(ImageSessionTable.updated_at.desc())
                .limit(1)
            )
            row = db.execute(stmt).scalar_one_or_none()
            return row.id if row else None
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_session_find_discord_failed", error=str(exc))
        return None


def get_session_meta(session_id: str) -> dict[str, Any]:
    try:
        conn = get_sync_connection()
        db = conn.get_session()
        try:
            row = db.get(ImageSessionTable, session_id)
            if row is None:
                return {}
            return {
                "operator_id": row.operator_id,
                "discord_user_id": row.discord_user_id,
                "discord_channel_id": row.discord_channel_id,
            }
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_session_meta_failed", session_id=session_id, error=str(exc))
        return {}
