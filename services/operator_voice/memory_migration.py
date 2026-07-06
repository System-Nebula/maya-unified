"""Copy legacy global voice memory into per-operator workspaces (idempotent)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from services.paths import DATA_DIR

log = logging.getLogger("maya-unified.memory_migration")

IMPORT_MARKER = ".imported-from-global"


def _operator_dir(operator_id: str) -> Path:
    path = DATA_DIR / "operators" / str(operator_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_memory_dir(operator_id: str) -> Path:
    path = _operator_dir(operator_id) / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _operator_memory_empty(operator_id: str) -> bool:
    mem_file = operator_memory_dir(operator_id) / "MEMORY.md"
    if not mem_file.is_file():
        return True
    text = mem_file.read_text(encoding="utf-8").strip().replace("§", "").strip()
    return not text


def _global_has_memory() -> bool:
    global_mem = DATA_DIR / "memory" / "MEMORY.md"
    if not global_mem.is_file():
        return False
    text = global_mem.read_text(encoding="utf-8").strip().replace("§", "").strip()
    return bool(text)


def copy_global_memory_to_operator(operator_id: str) -> bool:
    """Copy global memory/skills/DBs into operator dir once when operator memory is empty."""
    op_dir = _operator_dir(operator_id)
    marker = op_dir / IMPORT_MARKER
    if marker.is_file():
        return False
    if not _global_has_memory():
        return False
    if not _operator_memory_empty(operator_id):
        return False

    copied: list[str] = []
    global_memory = DATA_DIR / "memory"
    if global_memory.is_dir():
        dest_memory = op_dir / "memory"
        if dest_memory.exists():
            shutil.rmtree(dest_memory)
        shutil.copytree(global_memory, dest_memory)
        copied.append("memory/")

    global_skills = DATA_DIR / "skills"
    if global_skills.is_dir() and any(global_skills.glob("*.md")):
        dest_skills = op_dir / "skills"
        dest_skills.mkdir(parents=True, exist_ok=True)
        for md in global_skills.glob("*.md"):
            dest = dest_skills / md.name
            if not dest.is_file():
                shutil.copy2(md, dest)
        copied.append("skills/")

    for db_name in ("state.db", "cognitive.db"):
        src = DATA_DIR / db_name
        dest = op_dir / db_name
        if src.is_file() and not dest.is_file():
            shutil.copy2(src, dest)
            copied.append(db_name)

    marker.write_text("ok\n", encoding="utf-8")
    if copied:
        log.info("copied global memory -> operator %s: %s", operator_id, ", ".join(copied))
    return bool(copied)


def seed_operator_skills_from_examples(operator_id: str) -> None:
    """Copy bundled example skills into operator dir when skills/ is empty."""
    from services.voice.example_seed import EXAMPLES

    src_dir = EXAMPLES / "skills"
    if not src_dir.is_dir():
        return
    dest_dir = _operator_dir(operator_id) / "skills"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if any(dest_dir.glob("*.md")):
        return
    for md in sorted(src_dir.glob("*.md")):
        dest = dest_dir / md.name
        if not dest.is_file():
            shutil.copy2(md, dest)
