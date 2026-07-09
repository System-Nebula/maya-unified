"""Gateway play resolve — Andrea Botez setlist contract."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Repo-root tests/helpers (shared with tests/test_music_ontology_eval.py)
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "tests"))

from helpers.music_set_fixtures import ANDREA_URL, andrea_resolved_set
from maya_contracts import PlayResolveRequest
from maya_gateway.services.ontology_resolve import resolve_with_ontology


@pytest.mark.asyncio
async def test_play_resolve_andrea_botez_setlist():
    resolved = andrea_resolved_set()

    with patch(
        "services.music.url_handler.index_music_url",
        new=AsyncMock(return_value=resolved),
    ):
        resp = await resolve_with_ontology(PlayResolveRequest(query=ANDREA_URL))

    assert resp.matched_via == "setlist"
    assert len(resp.tracks) == 26
    assert "26 tracks" in (resp.explanation or "")

    first = resp.tracks[0]
    assert first.track_id == "yt:u1NHX9FcHVw:1"
    assert first.title == "Hard Bounce"
    assert first.start_offset_seconds == 0
    assert first.end_offset_seconds == 102
    assert first.set_key == "yt:u1NHX9FcHVw"
    assert first.set_position == 1
    assert first.play_mode == "seek"

    brisa = resp.tracks[3]
    assert brisa.start_offset_seconds == 4 * 60 + 34
    assert brisa.end_offset_seconds == 6 * 60 + 42
    assert brisa.track_id == "yt:u1NHX9FcHVw:4"

    last = resp.tracks[-1]
    assert last.set_position == 26
    assert last.start_offset_seconds == 55 * 60 + 30
