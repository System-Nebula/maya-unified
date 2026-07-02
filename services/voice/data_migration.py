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


def _load_personalities_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {"active": "", "personalities": {}}
    if not isinstance(data, dict):
        return {"active": "", "personalities": {}}
    personalities = data.get("personalities")
    if not isinstance(personalities, dict):
        personalities = {}
    active = str(data.get("active") or "")
    return {"active": active, "personalities": personalities}


def sync_legacy_personalities(*, force: bool = False) -> dict:
    """Merge legacy voice-runtime/data/personalities.json into data/personalities.json."""
    src = _qwen3_data_dir()
    if src is None:
        return {"ok": True, "skipped": True, "reason": "no legacy data directory"}
    src_file = src / "personalities.json"
    if not src_file.is_file():
        return {"ok": True, "skipped": True, "reason": "no legacy personalities.json"}

    dst = DATA_DIR
    dst.mkdir(parents=True, exist_ok=True)
    dst_file = dst / "personalities.json"
    src_data = _load_personalities_file(src_file)

    if not dst_file.is_file():
        dst_file.write_text(json.dumps(src_data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("copied legacy personalities -> %s", dst_file)
        return {"ok": True, "merged": True, "action": "copied"}

    dst_data = _load_personalities_file(dst_file)
    src_p = src_data["personalities"]
    dst_p = dict(dst_data["personalities"])
    changed = False

    for pid, entry in src_p.items():
        if not isinstance(entry, dict):
            continue
        current = dst_p.get(pid)
        if not isinstance(current, dict):
            dst_p[pid] = entry
            changed = True
            continue
        src_ts = float(entry.get("updated") or 0)
        dst_ts = float(current.get("updated") or 0)
        if force or src_ts > dst_ts:
            dst_p[pid] = entry
            changed = True

    active = dst_data["active"]
    src_active = src_data["active"]
    if src_active and src_active in dst_p:
        src_active_ts = float((src_p.get(src_active) or {}).get("updated") or 0)
        dst_active_ts = float((dst_p.get(active) or {}).get("updated") or 0) if active else 0.0
        if force or not active or src_active_ts >= dst_active_ts:
            active = src_active
            changed = True

    if not changed:
        return {"ok": True, "merged": False, "reason": "unified personalities already current"}

    merged = {"active": active, "personalities": dst_p}
    bak = dst / "personalities.pre-merge.json"
    if dst_file.is_file() and not bak.is_file():
        shutil.copy2(dst_file, bak)
    dst_file.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("merged legacy personalities into %s", dst_file)
    return {"ok": True, "merged": True, "active": active, "count": len(dst_p)}


def migrate_qwen3_data_to_unified(*, force: bool = False) -> dict:
    """Copy agent state from qwen3 into maya-unified/data (idempotent)."""
    src = _qwen3_data_dir()
    dst = DATA_DIR
    personality_sync = sync_legacy_personalities(force=force)
    if src is None:
        return {"ok": True, "skipped": True, "reason": "no qwen3 data directory", "personality_sync": personality_sync}

    dst.mkdir(parents=True, exist_ok=True)
    marker = dst / MARKER
    if marker.is_file() and not force:
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
            return {
                "ok": True,
                "skipped": True,
                "reason": "already migrated",
                "at": info.get("at"),
                "personality_sync": personality_sync,
            }
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
    if src_personalities.is_file() and not dst_personalities.is_file():
        shutil.copy2(src_personalities, dst_personalities)
        copied.append("personalities.json")
    elif personality_sync.get("merged"):
        copied.append("personalities.json (merged)")

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
    return {"ok": True, "already_migrated": not copied and bool(marker.exists()), "personality_sync": personality_sync, **manifest}
