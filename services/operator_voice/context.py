"""High-level per-operator voice context — seeding, sync to filesystem."""

from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from typing import Any

from maya_db import get_async_session
from sqlalchemy import select

from services.auth.operator_store import list_operators
from services.operator_voice import store as op_store
from services.operator_voice.paths import (
    load_legacy_global_personalities,
    load_legacy_global_settings,
    load_operator_personalities_file,
    seed_operator_dirs,
    sync_personalities_file,
    sync_settings_file,
)
from services.settings.schema import DEFAULT_SETTINGS, deep_merge

log = logging.getLogger("maya-unified.operator_voice")


def _sync_operator_files_from_data(
    operator_id: str | uuid.UUID,
    settings: dict,
    *,
    active: str,
    personalities: dict,
) -> None:
    """Write operator workspace files without nesting asyncio.run inside the gateway loop."""
    from services.operator_voice.memory_migration import copy_global_memory_to_operator

    sync_settings_file(operator_id, settings)
    sync_personalities_file(operator_id, active, personalities)
    seed_operator_dirs(operator_id)
    copy_global_memory_to_operator(str(operator_id))

def resolve_active_personality_id(
    personalities: dict[str, Any],
    *,
    file_active: str = "",
    settings_active_id: str = "",
) -> str:
    """Pick the personality slug to activate from file state and settings."""
    if not personalities:
        return ""
    if settings_active_id and settings_active_id in personalities:
        return settings_active_id
    if file_active and file_active in personalities:
        return file_active
    candidate = settings_active_id or file_active
    if candidate in personalities:
        return candidate
    return next(iter(personalities))


__all__ = [
    "ensure_operator_seeded",
    "import_legacy_global_to_admin",
    "load_settings",
    "save_settings",
    "load_personalities",
    "save_personalities",
    "append_turn",
    "get_conversation",
    "get_history_messages",
    "clear_conversation",
    "sync_operator_files",
    "reconcile_operator_personalities",
    "persist_operator_personalities_from_file",
    "resolve_active_personality_id",
]


async def _with_session(fn):
    async for session in get_async_session():
        result = await fn(session)
        await session.commit()
        return result
    return None


def load_settings(operator_id: str | uuid.UUID) -> dict[str, Any]:
    from services.async_bridge import run_sync

    async def _go(session):
        return await op_store.get_or_create_settings(session, operator_id)

    return run_sync(_with_session(_go))


def save_settings(operator_id: str | uuid.UUID, patch: dict[str, Any]) -> dict[str, Any]:
    from services.async_bridge import run_sync

    async def _go(session):
        merged = await op_store.save_settings(session, operator_id, patch)
        sync_settings_file(operator_id, merged)
        return merged

    return run_sync(_with_session(_go))


def load_personalities(operator_id: str | uuid.UUID) -> dict[str, Any]:
    from services.async_bridge import run_sync

    async def _go(session):
        return await op_store.get_or_create_personalities(session, operator_id)

    return run_sync(_with_session(_go))


def save_personalities(
    operator_id: str | uuid.UUID,
    *,
    active: str | None = None,
    personalities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.async_bridge import run_sync

    async def _go(session):
        data = await op_store.save_personalities(
            session, operator_id, active=active, personalities=personalities
        )
        sync_personalities_file(operator_id, data["active"], data["personalities"])
        return data

    return run_sync(_with_session(_go))


def append_turn(
    operator_id: str | uuid.UUID,
    role: str,
    content: str,
    *,
    message_id: str | None = None,
    corr_id: str | None = None,
    completion_id: str | None = None,
) -> None:
    from services.async_bridge import run_sync

    async def _go(session):
        await op_store.append_message(
            session,
            operator_id,
            role,
            content,
            message_id=message_id,
            corr_id=corr_id,
            completion_id=completion_id,
        )

    run_sync(_with_session(_go))


def get_conversation(operator_id: str | uuid.UUID) -> list[dict[str, str]]:
    from services.async_bridge import run_sync

    async def _go(session):
        return await op_store.get_conversation_turns(session, operator_id)

    return run_sync(_with_session(_go))


def clear_conversation(operator_id: str | uuid.UUID) -> int:
    from services.async_bridge import run_sync

    async def _go(session):
        return await op_store.clear_conversation(session, operator_id)

    return int(run_sync(_with_session(_go)) or 0)


def get_history_messages(operator_id: str | uuid.UUID, *, limit: int = 40) -> list[dict[str, str]]:
    from services.async_bridge import run_sync

    async def _go(session):
        return await op_store.history_as_messages(session, operator_id, limit=limit)

    return run_sync(_with_session(_go))


def sync_operator_files(operator_id: str | uuid.UUID) -> None:
    settings = load_settings(operator_id)
    pers = reconcile_operator_personalities(operator_id)
    sync_settings_file(operator_id, settings)
    sync_personalities_file(operator_id, pers.get("active", ""), pers.get("personalities", {}))
    seed_operator_dirs(operator_id)


def reconcile_operator_personalities(operator_id: str | uuid.UUID) -> dict[str, Any]:
    """Keep Postgres and personalities.json aligned — never wipe file data with an empty DB row."""
    file_data = load_operator_personalities_file(operator_id)
    file_pers = file_data.get("personalities") if isinstance(file_data.get("personalities"), dict) else {}
    file_active = str(file_data.get("active") or "")

    db_data = load_personalities(operator_id)
    db_pers = db_data.get("personalities") if isinstance(db_data.get("personalities"), dict) else {}
    db_active = str(db_data.get("active") or "")

    settings = load_settings(operator_id)
    settings_active = str(settings.get("personality", {}).get("active_id") or "")

    if file_pers and not db_pers:
        active = resolve_active_personality_id(
            file_pers,
            file_active=file_active or db_active,
            settings_active_id=settings_active,
        )
        save_personalities(operator_id, active=active, personalities=file_pers)
        return {"active": active, "personalities": file_pers}

    if db_pers:
        active = resolve_active_personality_id(
            db_pers,
            file_active=db_active or file_active,
            settings_active_id=settings_active,
        )
        sync_personalities_file(operator_id, active, db_pers)
        if active != db_active:
            save_personalities(operator_id, active=active, personalities=db_pers)
        return {"active": active, "personalities": db_pers}

    legacy = load_legacy_global_personalities()
    leg_pers = legacy.get("personalities") if isinstance(legacy.get("personalities"), dict) else {}
    if leg_pers:
        active = resolve_active_personality_id(
            leg_pers,
            file_active=str(legacy.get("active") or "default"),
            settings_active_id=settings_active,
        )
        save_personalities(operator_id, active=active, personalities=leg_pers)
        return {"active": active, "personalities": leg_pers}

    return {"active": file_active or db_active, "personalities": {}}


def persist_operator_personalities_from_file(operator_id: str | uuid.UUID) -> dict[str, Any]:
    """After a runtime personality mutation, mirror personalities.json back into Postgres."""
    raw = load_operator_personalities_file(operator_id)
    personalities = raw.get("personalities") if isinstance(raw.get("personalities"), dict) else {}
    active = str(raw.get("active") or "")
    return save_personalities(
        operator_id,
        active=active or None,
        personalities=personalities,
    )


from maya_db.models.operator_voice import OperatorVoiceSettings


async def ensure_operator_seeded(session, operator_id: str | uuid.UUID) -> bool:
    """Seed defaults for a new operator. Returns True if newly seeded."""
    oid = uuid.UUID(str(operator_id))
    existing = await session.get(OperatorVoiceSettings, oid)
    if existing is not None:
        seed_operator_dirs(operator_id)
        pers_row = await op_store.get_or_create_personalities(session, oid)
        db_pers = pers_row.get("personalities") if isinstance(pers_row.get("personalities"), dict) else {}
        file_data = load_operator_personalities_file(operator_id)
        file_pers = file_data.get("personalities") if isinstance(file_data.get("personalities"), dict) else {}
        if file_pers and not db_pers:
            active = str(file_data.get("active") or pers_row.get("active") or "default")
            await op_store.save_personalities(session, oid, active=active, personalities=file_pers)
            pers_row = {"active": active, "personalities": file_pers}
        if not db_pers and not file_pers:
            legacy = load_legacy_global_personalities()
            leg_pers = legacy.get("personalities") if isinstance(legacy.get("personalities"), dict) else {}
            if leg_pers:
                settings_row = existing.settings if isinstance(existing.settings, dict) else {}
                settings_active = str(settings_row.get("personality", {}).get("active_id") or "")
                active = resolve_active_personality_id(
                    leg_pers,
                    file_active=str(legacy.get("active") or "default"),
                    settings_active_id=settings_active,
                )
                await op_store.save_personalities(session, oid, active=active, personalities=leg_pers)
                pers_row = {"active": active, "personalities": leg_pers}
        _sync_operator_files_from_data(
            operator_id,
            existing.settings if isinstance(existing.settings, dict) else {},
            active=str(pers_row.get("active") or "default"),
            personalities=pers_row.get("personalities") or {},
        )
        return False
    settings = deepcopy(DEFAULT_SETTINGS)
    personalities_data = load_legacy_global_personalities()
    if not personalities_data.get("personalities"):
        personalities_data = {"active": "default", "personalities": {}}
    active = str(personalities_data.get("active") or "default")
    personalities = personalities_data.get("personalities") or {}
    await op_store.save_settings(session, oid, settings)
    await op_store.save_personalities(
        session,
        oid,
        active=active,
        personalities=personalities,
    )
    _sync_operator_files_from_data(operator_id, settings, active=active, personalities=personalities)
    log.info("seeded operator voice workspace %s", operator_id)
    return True


async def import_legacy_global_to_admin(session) -> bool:
    """One-time: copy global data/*.json into first admin if no operator settings exist."""
    if await op_store.any_operator_settings_exist(session):
        return False
    from maya_db.models.operator import OperatorUser

    admin = await session.scalar(
        select(OperatorUser).where(OperatorUser.role == "admin").order_by(OperatorUser.created_at).limit(1)
    )
    if admin is None:
        ops = await list_operators(session)
        if not ops:
            return False
        admin = ops[0]
    settings = load_legacy_global_settings()
    pers = load_legacy_global_personalities()
    active = str(pers.get("active") or "default")
    personalities = pers.get("personalities") or {}
    await op_store.save_settings(session, admin.id, settings)
    await op_store.save_personalities(
        session,
        admin.id,
        active=active,
        personalities=personalities,
    )
    _sync_operator_files_from_data(admin.id, settings, active=active, personalities=personalities)
    log.info("imported legacy global voice data -> admin operator %s", admin.username)
    return True
