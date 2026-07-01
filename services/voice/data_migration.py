"""One-time migration: packages/voice-runtime/data → data/."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from services.paths import DATA_DIR, VOICE_RUNTIME

log = logging.getLogger("maya-unified.migration")

MARKER = ".migrated-from-qwen3"
SKIP_FILES = frozenset({"settings.json"})


def _qwen3_data_dir() -> Path | None:
    src = VOICE_RUNTIME / "data"
    return src if src.is_dir() else None


def migrate_qwen3_data_to_unified(*, force: bool = False) -> dict:
    """Copy agent state from qwen3 into maya-unified/data (idempotent)."""
    src = _qwen3_data_dir()
    dst = DATA_DIR
    if src is None:
        return {"ok": True, "skipped": True, "reason": "no qwen3 data directory"}

    dst.mkdir(parents=True, exist_ok=True)
    marker = dst / MARKER
    if marker.is_file() and not force:
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
            return {"ok": True, "skipped": True, "reason": "already migrated", "at": info.get("at")}
        except (OSError, TypeError, ValueError):
            pass

    copied: list[str] = []
    skipped: list[str] = []

    for dirname in ("memory", "skills"):
        sdir = src / dirname
        if not sdir.is_dir():
            continue
        ddir = dst / dirname
        if ddir.exists() and not force:
            skipped.append(f"{dirname}/ (exists)")
            continue
        shutil.copytree(sdir, ddir, dirs_exist_ok=True)
        copied.append(f"{dirname}/")

    for fname in ("cognitive.db", "state.db"):
        if fname in SKIP_FILES:
            continue
        sfile = src / fname
        if not sfile.is_file():
            continue
        dfile = dst / fname
        if dfile.exists() and not force:
            skipped.append(f"{fname} (exists)")
            continue
        shutil.copy2(sfile, dfile)
        copied.append(fname)

    src_personalities = src / "personalities.json"
    dst_personalities = dst / "personalities.json"
    if src_personalities.is_file():
        should_copy = force or not dst_personalities.is_file()
        if not should_copy and dst_personalities.is_file():
            try:
                src_n = len(json.loads(src_personalities.read_text(encoding="utf-8")).get("personalities", {}))
                dst_n = len(json.loads(dst_personalities.read_text(encoding="utf-8")).get("personalities", {}))
                should_copy = src_n > dst_n
            except (OSError, TypeError, ValueError):
                should_copy = src_personalities.stat().st_size > dst_personalities.stat().st_size
        if should_copy:
            if dst_personalities.is_file():
                bak = dst / "personalities.pre-migration.json"
                if not bak.is_file():
                    shutil.copy2(dst_personalities, bak)
            shutil.copy2(src_personalities, dst_personalities)
            copied.append("personalities.json")
        else:
            skipped.append("personalities.json (unified kept)")

    for item in src.iterdir():
        if not item.is_file() or item.name in SKIP_FILES or item.name == MARKER:
            continue
        if item.suffix in {".db", ".json"} and item.name != "personalities.json":
            dfile = dst / item.name
            if dfile.exists() and not force:
                skipped.append(f"{item.name} (exists)")
                continue
            shutil.copy2(item, dfile)
            copied.append(item.name)

    manifest = {
        "at": datetime.now(timezone.utc).isoformat(),
        "source": str(src.resolve()),
        "destination": str(dst.resolve()),
        "copied": copied,
        "unchanged": skipped,
    }
    marker.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if copied:
        log.info("migrated qwen3 data → %s: %s", dst, ", ".join(copied))
    else:
        log.info("qwen3 data migration: nothing new to copy (%s)", dst)
    return {"ok": True, "already_migrated": not copied and bool(marker.exists()), **manifest}
