"""Offline fetch caches for Playwright / e2e runs (``MAYA_E2E_FIXTURES=1``)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANDREA_FIXTURES = _REPO_ROOT / "tests" / "tracklists" / "youtube" / "fixtures"

ANDREA_YT_URL = "https://www.youtube.com/watch?v=u1NHX9FcHVw"
ANDREA_YT_URL_SHORT = "https://youtu.be/u1NHX9FcHVw"


def seed_andrea_fetch_cache() -> None:
    """Pre-populate url cache so Andrea setlist resolve runs without network."""
    from services.music.url_cache import cache_set

    ytdlp_path = _ANDREA_FIXTURES / "andrea_botez_ytdlp_info.json"
    desc_path = _ANDREA_FIXTURES / "andrea_botez_description.txt"
    if not ytdlp_path.is_file() or not desc_path.is_file():
        log.warning("andrea e2e fixtures missing under %s", _ANDREA_FIXTURES)
        return

    info = json.loads(ytdlp_path.read_text())
    description = desc_path.read_text()
    info = {**info, "description": description}

    for url in (
        ANDREA_YT_URL,
        ANDREA_YT_URL_SHORT,
        f"{ANDREA_YT_URL_SHORT}?list=RDu1NHX9FcHVw",
        f"{ANDREA_YT_URL}&list=RDu1NHX9FcHVw",
    ):
        cache_set("ytdlp", url, info)

    log.info("seeded andrea youtube cache for e2e (%d urls)", 4)
