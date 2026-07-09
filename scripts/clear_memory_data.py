#!/usr/bin/env python3
"""Clear Postgres chat history and file-backed memory for all operators + legacy data."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data"
MEMORY_FILES = ("MEMORY.md", "USER.md")
MEMORY_SUBDIRS = ("users", "guilds")
DB_FILES = ("state.db", "cognitive.db")


def _clear_filesystem_memory(data_dir: Path) -> None:
    mem = data_dir / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    for name in MEMORY_FILES:
        path = mem / name
        path.write_text("", encoding="utf-8")
    for sub in MEMORY_SUBDIRS:
        path = mem / sub
        if path.is_dir():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    skills = data_dir / "skills"
    if skills.is_dir():
        for skill in skills.glob("*.md"):
            skill.unlink(missing_ok=True)
    for db_name in DB_FILES:
        (data_dir / db_name).unlink(missing_ok=True)


async def _clear_postgres() -> int:
    from maya_db import get_async_session
    from maya_db.models.operator_voice import (
        OperatorConversationMessage,
        OperatorConversationSession,
    )
    from sqlalchemy import delete

    deleted = 0
    async for session in get_async_session():
        result = await session.execute(delete(OperatorConversationMessage))
        deleted = int(result.rowcount or 0)
        await session.execute(delete(OperatorConversationSession))
        await session.commit()
        break
    return deleted


def main() -> None:
    targets: list[Path] = [DATA]
    operators = DATA / "operators"
    if operators.is_dir():
        targets.extend(p for p in operators.iterdir() if p.is_dir())

    for data_dir in targets:
        _clear_filesystem_memory(data_dir)
        print(f"cleared filesystem memory: {data_dir}")

    deleted = asyncio.run(_clear_postgres())
    print(f"cleared postgres conversation messages: {deleted}")


if __name__ == "__main__":
    main()
