"""Copy bundled examples into runtime directories on first launch."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from services.paths import DATA_DIR, ROOT, voices_dir

log = logging.getLogger("maya-unified.example_seed")

EXAMPLES = ROOT / "examples"


def seed_examples_if_needed() -> None:
    """Idempotent: voice clip, personalities, and starter skills."""
    seed_voice_if_needed()
    seed_personality_if_needed()
    seed_skills_if_needed()


def seed_voice_if_needed() -> None:
    src_wav = EXAMPLES / "voices" / "ref.wav"
    if not src_wav.is_file():
        return
    dest_dir = voices_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_wav = dest_dir / "ref.wav"
    dest_txt = dest_dir / "ref.txt"
    if not dest_wav.is_file():
        shutil.copy2(src_wav, dest_wav)
        log.info("seeded demo voice -> %s", dest_wav)
    src_txt = EXAMPLES / "voices" / "ref.txt"
    if src_txt.is_file() and not dest_txt.is_file():
        shutil.copy2(src_txt, dest_txt)


def seed_personality_if_needed() -> None:
    bundle = EXAMPLES / "personalities" / "personalities.json"
    legacy = EXAMPLES / "personalities" / "maya-default.json"
    source = bundle if bundle.is_file() else legacy
    if not source.is_file():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = DATA_DIR / "personalities.json"
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("personalities"):
                return
        except (OSError, TypeError, ValueError):
            pass
    try:
        seed = json.loads(source.read_text(encoding="utf-8"))
        target.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("seeded personalities from %s", source.name)
    except (OSError, TypeError, ValueError) as exc:
        log.warning("personality seed skipped: %s", exc)


def seed_skills_if_needed() -> None:
    src_dir = EXAMPLES / "skills"
    if not src_dir.is_dir():
        return
    dest_dir = DATA_DIR / "skills"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for md in sorted(src_dir.glob("*.md")):
        dest = dest_dir / md.name
        if dest.is_file():
            continue
        shutil.copy2(md, dest)
        log.info("seeded skill -> %s", dest.name)
