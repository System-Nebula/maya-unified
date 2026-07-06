"""Tests for music_lookup ToolSpec handler."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_VR = _ROOT / "packages" / "voice-runtime"
if str(_VR) not in sys.path:
    sys.path.insert(0, str(_VR))

from maya_contracts import TrackMetadata, SourceRefModel  # noqa: E402
from tools.music_ontology import build_music_ontology_tools  # noqa: E402


def test_music_lookup_empty_query() -> None:
    tools = build_music_ontology_tools()
    lookup = next(t for t in tools if t.name == "music_lookup")
    out = lookup.handler({"query": "  "})
    assert out["ok"] is False


def test_music_lookup_returns_structured_dict() -> None:
    meta = TrackMetadata(
        title="Midnight City",
        artist="M83",
        work_key="wd:Q1",
        source_refs=[SourceRefModel(schema_id="wd", external_id="Q1")],
        confidence=0.88,
    )
    tools = build_music_ontology_tools()
    lookup = next(t for t in tools if t.name == "music_lookup")
    with patch("services.music.ontology.lookup_sync", return_value=meta):
        out = lookup.handler({"query": "M83 Midnight City"})
    assert out["ok"] is True
    assert out["found"] is True
    assert out["work_key"] == "wd:Q1"
