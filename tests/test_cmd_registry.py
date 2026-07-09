"""Tests for cmd_registry core behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.dispatcher import dispatch_cmd_async
from services.cmd.models import CmdContext, CmdDefinition, CmdParameter, CmdResult, CmdSurface
from services.cmd.parser import parse_cmd_input, validate_args
from services.cmd.registry import registry


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    from services.cmd import bootstrap

    monkeypatch.setattr(bootstrap, "_bootstrapped", False)
    registry._by_id.clear()
    registry._alias_index.clear()
    ensure_cmds_registered()


@pytest.fixture
def imagine_preflight_ok():
    """Stub the settings/health preflight so dispatch tests stay unit-level."""
    with (
        patch(
            "services.settings.store.load_effective_settings",
            return_value={"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"}},
        ),
        patch(
            "services.imagine.health.get_cached_comfyui_health",
            return_value={
                "status": "ok",
                "url": "http://127.0.0.1:3030",
                "weights": {
                    "ok": True,
                    "zit": {"ok": True, "missing": [], "detail": "ok"},
                    "krea2": {"ok": True, "missing": [], "detail": "ok", "capability": {"ok": True}},
                },
            },
        ),
        patch(
            "services.imagine.health.apply_comfyui_url_from_settings",
            return_value="http://127.0.0.1:3030",
        ),
    ):
        yield


def test_discovery_excludes_executor():
    help_cmd = registry.get("help")
    assert help_cmd is not None
    payload = help_cmd.discovery_dict()
    assert "executor" not in payload
    assert payload["id"] == "help"
    assert "chat" in payload["surfaces"]


def test_alias_resolution():
    parsed = parse_cmd_input("/img cyberpunk alley")
    assert parsed is not None
    assert parsed.cmd_id == "imagine"
    assert parsed.args["prompt"] == "cyberpunk alley"


def test_validate_missing_required_parameter():
    cmd = registry.get("imagine")
    assert cmd is not None
    assert validate_args(cmd, {}) == "missing required parameter: prompt"


def test_registry_discovery_by_surface():
    from services.game.enabled import GAME_MODE_ENABLED

    dashboard_cmds = registry.discovery(surface=CmdSurface.DASHBOARD)
    ids = {item["id"] for item in dashboard_cmds}
    expected = {"help", "status", "imagine", "blend", "play"}
    if GAME_MODE_ENABLED:
        expected.add("game")
    assert expected.issubset(ids)


@pytest.mark.asyncio
async def test_dispatch_help():
    parsed = parse_cmd_input("/help")
    assert parsed is not None
    result = await dispatch_cmd_async(
        parsed,
        CmdContext(surface=CmdSurface.CHAT),
    )
    assert result.ok is True
    assert "Available cmds" in result.text


@pytest.mark.asyncio
async def test_dispatch_imagine_async(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine neon alley")
    assert parsed is not None
    mock_result = {
        "job_id": "job-123",
        "status": "completed",
        "output_url": "https://example.com/out.png",
        "workflow_id": "a0000001-0000-4000-8000-000000000004",
        "provider_key": "comfyui:graph",
    }
    mock_run = AsyncMock(return_value=mock_result)
    with patch("services.cmd.executors.imagine.run_imagine_job", mock_run):
        result = await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, operator_id="op-1"),
        )
    assert mock_run.call_args.kwargs["model"] == "zit"
    assert result.ok is True
    assert result.artifacts[0]["url"] == "https://example.com/out.png"
    assert result.artifacts[0]["job_id"] == "job-123"
    assert result.text == "Image ready."
    assert "job-123" not in result.text


@pytest.mark.asyncio
async def test_dispatch_imagine_defaults_zit_on_dashboard(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine a doge shiba inu anime style")
    assert parsed is not None
    mock_run = AsyncMock(
        return_value={
            "job_id": "job-doge",
            "status": "completed",
            "output_url": "https://example.com/doge.png",
            "workflow_id": "a0000001-0000-4000-8000-000000000004",
            "provider_key": "comfyui:graph",
        }
    )
    with patch("services.cmd.executors.imagine.run_imagine_job", mock_run):
        await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, operator_id="op-1"),
        )
    assert mock_run.call_args.kwargs["model"] == "zit"
    assert mock_run.call_args.kwargs["prompt"] == "a doge shiba inu anime style"


@pytest.mark.asyncio
async def test_dispatch_imagine_uses_settings_default_model(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine a cat")
    assert parsed is not None
    settings = {
        "imagine": {
            "enabled": True,
            "comfyui_url": "http://127.0.0.1:3030",
            "default_model": "krea2",
        }
    }
    mock_run = AsyncMock(
        return_value={
            "job_id": "job-cat",
            "status": "completed",
            "output_url": "https://example.com/cat.png",
            "workflow_id": "a0000001-0000-4000-8000-000000000005",
            "provider_key": "comfyui:graph",
        }
    )
    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.cmd.executors.imagine.run_imagine_job", mock_run),
    ):
        await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, operator_id="op-1"),
        )
    assert mock_run.call_args.kwargs["model"] == "krea2"


def test_parse_imagine_splits_inline_model_arg() -> None:
    parsed = parse_cmd_input("/imagine sunset model=krea2")
    assert parsed is not None
    assert parsed.args["prompt"] == "sunset"
    assert parsed.args["model"] == "krea2"


def test_parse_imagine_splits_multiple_inline_args() -> None:
    parsed = parse_cmd_input('/imagine sunset over mountains model=krea2 size=512x512')
    assert parsed is not None
    assert parsed.args["prompt"] == "sunset over mountains"
    assert parsed.args["model"] == "krea2"
    assert parsed.args["size"] == "512x512"


def test_parse_imagine_explicit_prompt_kwarg() -> None:
    parsed = parse_cmd_input("/imagine prompt=sunset model=krea2")
    assert parsed is not None
    assert parsed.args["prompt"] == "sunset"
    assert parsed.args["model"] == "krea2"


def test_cmd_result_to_chat_response_includes_correlation_fields() -> None:
    payload = CmdResult(
        ok=False,
        error="failed",
        trace_id="trace-abc",
        job_id="job-42",
        corr_id="c_test",
    ).to_chat_response()
    assert payload["ok"] is False
    assert payload["error"] == "failed"
    assert payload["trace_id"] == "trace-abc"
    assert payload["job_id"] == "job-42"
    assert payload["corr_id"] == "c_test"


@pytest.mark.asyncio
async def test_dispatch_imagine_failure_includes_trace_and_job_ids(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine neon alley")
    assert parsed is not None
    mock_run = AsyncMock(
        return_value={
            "job_id": "job-fail",
            "status": "failed",
            "output_url": "",
            "workflow_id": "wf-1",
            "provider_key": "comfyui:graph",
        }
    )
    with (
        patch("services.cmd.executors.imagine.run_imagine_job", mock_run),
        patch("services.cmd.executors.imagine._trace_id", return_value="trace-imagine"),
    ):
        result = await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, operator_id="op-1"),
        )
    assert result.ok is False
    assert result.trace_id == "trace-imagine"
    assert result.job_id == "job-fail"


@pytest.mark.asyncio
async def test_dispatch_failure_backfills_trace_id():
    def _fail(_ctx, _args):
        return CmdResult(ok=False, error="boom")

    registry.register(
        CmdDefinition(
            id="failcmd",
            name="failcmd",
            description="Always fails",
            category="Utilities",
            surfaces=[CmdSurface.CHAT],
            executor=_fail,
        )
    )
    parsed = parse_cmd_input("/failcmd")
    assert parsed is not None
    with patch("services.cmd.dispatcher._cmd_trace_id", return_value="trace-dispatch"):
        result = await dispatch_cmd_async(parsed, CmdContext(surface=CmdSurface.CHAT))
    assert result.ok is False
    assert result.trace_id == "trace-dispatch"


def test_unknown_slash_is_not_parsed():
    assert parse_cmd_input("/not-a-real-cmd") is None


def test_custom_cmd_registration():
    def _echo(_ctx, args):
        return CmdResult(ok=True, text=str(args.get("text", "")))

    registry.register(
        CmdDefinition(
            id="echo",
            name="echo",
            description="Echo text",
            category="Utilities",
            parameters=[CmdParameter(name="text", type="string", required=True)],
            surfaces=[CmdSurface.CHAT],
            executor=_echo,
        )
    )
    parsed = parse_cmd_input("/echo hello world")
    assert parsed is not None
    assert parsed.args["text"] == "hello world"


def _fake_yt_dlp(info):
    """Return a stand-in yt_dlp module whose YoutubeDL yields ``info``."""
    import types

    class _YDL:
        def __init__(self, _opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def extract_info(self, _url, download=False):
            return info

    return types.SimpleNamespace(YoutubeDL=_YDL)


def test_parse_play_url_resolves_to_play() -> None:
    parsed = parse_cmd_input("/play https://00000ooooo.bandcamp.com/album/--5")
    assert parsed is not None
    assert parsed.cmd_id == "play"


def test_parse_play_alias_resolves_to_play() -> None:
    parsed = parse_cmd_input("/p https://00000ooooo.bandcamp.com/album/--5")
    assert parsed is not None
    assert parsed.cmd_id == "play"


def test_play_extracts_full_url_from_raw_text() -> None:
    from services.cmd.executors.play import _extract_query

    ctx = CmdContext(
        surface=CmdSurface.DASHBOARD,
        raw_text="/play https://00000ooooo.bandcamp.com/album/--5",
    )
    assert _extract_query(ctx) == "https://00000ooooo.bandcamp.com/album/--5"


def test_play_extracts_multiword_search() -> None:
    from services.cmd.executors.play import _extract_query

    ctx = CmdContext(raw_text="/play daft punk one more time")
    assert _extract_query(ctx) == "daft punk one more time"


def test_play_bare_extracts_empty() -> None:
    from services.cmd.executors.play import _extract_query

    assert _extract_query(CmdContext(raw_text="/play")) == ""


def test_expand_playlist_album(monkeypatch) -> None:
    import sys

    from services.discord import playlist

    info = {
        "title": "Album X",
        "entries": [
            {"url": "https://x.bandcamp.com/track/a", "title": "A"},
            {"url": "https://x.bandcamp.com/track/b", "title": "B"},
        ],
    }
    monkeypatch.setitem(sys.modules, "yt_dlp", _fake_yt_dlp(info))
    monkeypatch.setattr("services.discord.youtube_patch._cookie_opts", lambda: {})

    result = playlist.expand_playlist("https://x.bandcamp.com/album/--5")
    assert result is not None
    assert result.title == "Album X"
    assert [t[0] for t in result.tracks] == [
        "https://x.bandcamp.com/track/a",
        "https://x.bandcamp.com/track/b",
    ]


def test_expand_playlist_single_track_returns_none(monkeypatch) -> None:
    import sys

    from services.discord import playlist

    info = {"title": "Song", "webpage_url": "https://x.bandcamp.com/track/a"}
    monkeypatch.setitem(sys.modules, "yt_dlp", _fake_yt_dlp(info))
    monkeypatch.setattr("services.discord.youtube_patch._cookie_opts", lambda: {})

    assert playlist.expand_playlist("https://x.bandcamp.com/track/a") is None


def test_expand_playlist_non_url_returns_none() -> None:
    from services.discord import playlist

    assert playlist.expand_playlist("daft punk one more time") is None


def test_stream_src_percent_encodes_query() -> None:
    from services.dashboard.player import stream_src

    assert stream_src("https://x.bandcamp.com/track/a b") == (
        "/api/media/stream?q=https%3A%2F%2Fx.bandcamp.com%2Ftrack%2Fa%20b"
    )


def test_playlist_artifact_album() -> None:
    from services.dashboard.player import build_playlist_artifact
    from services.discord.playlist import PlaylistExpansion

    exp = PlaylistExpansion(title="Album X", tracks=[("https://x/t1", "One"), ("https://x/t2", "Two")])
    art = build_playlist_artifact("https://x/album", exp)
    assert art["type"] == "playlist"
    assert art["title"] == "Album X"
    assert art["url"] == "https://x/album"  # x-for :key
    assert [t["title"] for t in art["tracks"]] == ["One", "Two"]
    assert art["tracks"][0]["query"] == "https://x/t1"
    assert art["tracks"][0]["src"].startswith("/api/media/stream?q=")


def test_playlist_artifact_single_search() -> None:
    from services.dashboard.player import build_playlist_artifact

    art = build_playlist_artifact("daft punk one more time", None)
    assert art["type"] == "playlist"
    assert len(art["tracks"]) == 1
    assert art["tracks"][0]["title"] == "daft punk one more time"


def test_media_resolve_target() -> None:
    from apps.gateway.music_routes import _resolve_target

    assert _resolve_target("https://x.bandcamp.com/album/--5") == "https://x.bandcamp.com/album/--5"
    assert _resolve_target("daft punk") == "ytsearch1:daft punk"


@pytest.mark.asyncio
async def test_dispatch_play_dashboard_emits_playlist(monkeypatch) -> None:
    import sys
    import types

    from services.discord.playlist import PlaylistExpansion

    fake_hub = types.ModuleType("services.voice.hub")
    broadcasts: list[dict] = []

    class _Hub:
        ready = False
        agent = None

        @staticmethod
        def broadcast(event, *, operator_id=None, room_id=None):
            broadcasts.append(event)

    fake_hub.hub = _Hub()
    monkeypatch.setitem(sys.modules, "services.voice.hub", fake_hub)
    monkeypatch.setattr(
        "services.discord.playlist.expand_playlist",
        lambda _q: PlaylistExpansion(title="Album X", tracks=[("u/a", "A"), ("u/b", "B")]),
    )

    parsed = parse_cmd_input("/play https://x.bandcamp.com/album/--5")
    assert parsed is not None
    result = await dispatch_cmd_async(
        parsed,
        CmdContext(surface=CmdSurface.DASHBOARD, raw_text="/play https://x.bandcamp.com/album/--5"),
    )
    assert result.ok is True
    assert not result.artifacts
    assert "Queued 2 tracks" in (result.text or "")
    load_events = [e for e in broadcasts if e.get("type") == "player.load"]
    assert len(load_events) == 1
    assert load_events[0]["playlist"]["type"] == "playlist"
    assert len(load_events[0]["playlist"]["tracks"]) == 2


def test_player_cache_remembers_playlist_and_position() -> None:
    from services.dashboard.player import (
        build_playlist_artifact,
        player_snapshot,
        remember_player_control,
        remember_player_load,
    )
    from services.discord.playlist import PlaylistExpansion

    exp = PlaylistExpansion(title="Album X", tracks=[("https://x/t1", "One"), ("https://x/t2", "Two")])
    playlist = build_playlist_artifact("https://x/album", exp)
    remember_player_load(playlist, operator_id="op1")
    remember_player_control("skip", operator_id="op1")
    snap = player_snapshot("op1")
    assert snap is not None
    assert snap["current"] == 1
    assert snap["tracks"][1]["query"] == "https://x/t2"


def test_player_cache_clear_removes_state() -> None:
    from services.dashboard.player import (
        build_playlist_artifact,
        player_snapshot,
        remember_player_control,
        remember_player_load,
    )
    from services.discord.playlist import PlaylistExpansion

    exp = PlaylistExpansion(title="Album X", tracks=[("https://x/t1", "One")])
    playlist = build_playlist_artifact("https://x/album", exp)
    remember_player_load(playlist, operator_id="op1")
    remember_player_control("clear", operator_id="op1")
    assert player_snapshot("op1") is None


def test_expand_playlist_youtube_id_fallback(monkeypatch) -> None:
    import sys

    from services.discord import playlist

    info = {
        "title": "Mix",
        "extractor": "youtube:tab",
        "entries": [
            {"id": "abc12345678", "title": "Song A", "ie_key": "Youtube"},
        ],
    }
    monkeypatch.setitem(sys.modules, "yt_dlp", _fake_yt_dlp(info))
    monkeypatch.setattr("services.discord.youtube_patch._cookie_opts", lambda: {})

    result = playlist.expand_playlist("https://www.youtube.com/playlist?list=PLx")
    assert result is not None
    assert result.tracks[0][0] == "https://www.youtube.com/watch?v=abc12345678"


def test_parse_imagine_hidden_arena_mode() -> None:
    parsed = parse_cmd_input("/imagine cat astronaut mode=arena")
    assert parsed is not None
    assert parsed.args["prompt"] == "cat astronaut"
    assert parsed.args["mode"] == "arena"


def test_validate_imagine_accepts_hidden_arena_mode() -> None:
    cmd = registry.get("imagine")
    assert cmd is not None
    assert validate_args(cmd, {"prompt": "sunset", "mode": "arena"}) is None


def test_validate_imagine_rejects_unknown_mode() -> None:
    cmd = registry.get("imagine")
    assert cmd is not None
    err = validate_args(cmd, {"prompt": "sunset", "mode": "edit"})
    assert err is not None
    assert "mode" in err


def test_imagine_discovery_hides_arena_mode() -> None:
    cmd = registry.get("imagine")
    assert cmd is not None
    mode_param = next(p for p in cmd.discovery_dict()["parameters"] if p["name"] == "mode")
    assert mode_param["choices"] == ["generate"]
    assert "hidden_choices" not in mode_param
    assert "arena" not in mode_param.get("choices", [])


@pytest.mark.asyncio
async def test_dispatch_imagine_arena_mode(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine fox in rain mode=arena")
    assert parsed is not None
    mock_arena = AsyncMock(
        return_value={
            "battle_id": "battle-1",
            "status": "completed",
            "both_failed": False,
            "slots": {
                "a": {"url": "/imagine-outputs/a.png", "gen_ms": 1000, "status": "completed"},
                "b": {"url": "/imagine-outputs/b.png", "gen_ms": 1200, "status": "completed"},
            },
        }
    )
    with patch("services.cmd.executors.imagine.run_arena_job", mock_arena):
        result = await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.CHAT, operator_id="op-1"),
        )
    assert result.ok is True
    assert result.text.startswith("Arena ready")
    assert result.artifacts[0]["type"] == "arena"
    assert result.artifacts[0]["battle_id"] == "battle-1"
    assert result.artifacts[0]["image_a"] == "/imagine-outputs/a.png"
    assert "model_a" not in result.artifacts[0]
    import json

    json.dumps(result.artifacts[0])
