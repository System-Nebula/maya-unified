"""Tests for dashboard queue direct routing."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
VOICE_RUNTIME = ROOT / "packages" / "voice-runtime"
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))


def _queue_spec():
    from tools.dashboard_player import build_dashboard_player_tools

    return next(t for t in build_dashboard_player_tools() if t.name == "dashboard_queue_music")


def test_queue_music_async_returns_pending_ack() -> None:
    spec = _queue_spec()
    with patch("services.dashboard.resolve.schedule_queue_resolve") as mock_schedule:
        out = spec.handler({"query": "gangnam style", "after_current": True})
    assert out["ok"] is True
    assert out.get("pending") is True
    assert "Looking up" in out["message"]
    mock_schedule.assert_called_once()
    assert mock_schedule.call_args.kwargs.get("after_current") is True


def test_queue_music_async_append_tail() -> None:
    spec = _queue_spec()
    with patch("services.dashboard.resolve.schedule_queue_resolve") as mock_schedule:
        out = spec.handler({"query": "hyuna bubble pop"})
    assert out["ok"] is True
    mock_schedule.assert_called_once()
    assert mock_schedule.call_args.kwargs.get("after_current") is False


def test_queue_music_sync_handler() -> None:
    spec = _queue_spec()
    artifact = {
        "type": "playlist",
        "title": "Test",
        "tracks": [{"title": "T", "query": "ytsearch1:test", "src": "/x"}],
    }
    with patch("services.dashboard.resolve.resolve_playlist_blocking", return_value=artifact):
        with patch("services.dashboard.player.remember_player_append") as mock_append:
            mock_append.return_value = artifact
            with patch("services.voice.hub.hub") as mock_hub:
                mock_hub._active_operator_id = "op-1"
                out = spec.handler({"query": "test track", "sync": True})
    assert out["ok"] is True
    assert "Added" in out["message"]
