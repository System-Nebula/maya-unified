"""Monkey-patch qwen3 discord_bot YouTube helpers (read-only upstream)."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from services.settings.store import load_settings

log = logging.getLogger("maya-unified.discord.youtube")

_PATCHED = "_unified_youtube_patch"
_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})")
_DEFAULT_CLIENTS = ["android", "web"]
_SEARCH_RESULTS = 5


def _discord_youtube_settings() -> dict[str, Any]:
    disc = load_settings().get("discord") or {}
    if not isinstance(disc, dict):
        return {}
    return disc


def _player_clients() -> list[str]:
    raw = _discord_youtube_settings().get("youtube_player_clients")
    if isinstance(raw, list) and raw:
        return [str(c).strip() for c in raw if str(c).strip()]
    if isinstance(raw, str) and raw.strip():
        return [c.strip() for c in raw.split(",") if c.strip()]
    return list(_DEFAULT_CLIENTS)


def _cookie_opts() -> dict[str, Any]:
    disc = _discord_youtube_settings()
    browser = str(disc.get("youtube_cookies_browser") or "").strip().lower()
    cookie_file = str(disc.get("youtube_cookies_file") or "").strip()
    opts: dict[str, Any] = {}
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if path.is_file():
            opts["cookiefile"] = str(path)
        else:
            log.warning("youtube cookies file not found: %s", cookie_file)
    elif browser:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


def _base_ytdlp_opts(*, flat: bool = False) -> dict[str, Any]:
    clients = _player_clients()
    opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": clients}},
    }
    opts.update(_cookie_opts())
    if flat:
        opts["extract_flat"] = "in_playlist"
        opts["default_search"] = f"ytsearch{_SEARCH_RESULTS}"
    return opts


def _extractor_args_cli() -> list[str]:
    clients = ",".join(_player_clients())
    return ["--extractor-args", f"youtube:player_client={clients}"]


def _cookie_cli_args() -> list[str]:
    disc = _discord_youtube_settings()
    browser = str(disc.get("youtube_cookies_browser") or "").strip().lower()
    cookie_file = str(disc.get("youtube_cookies_file") or "").strip()
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if path.is_file():
            return ["--cookies", str(path)]
        log.warning("youtube cookies file not found: %s", cookie_file)
        return []
    if browser:
        return ["--cookies-from-browser", browser]
    return []


def _normalize_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is required")
    return q


def _is_video_id(value: str) -> bool:
    return bool(value and len(value) == 11 and re.fullmatch(r"[\w-]{11}", value))


def _entry_video_url(entry: dict[str, Any]) -> str | None:
    url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
    vid = str(entry.get("id") or "").strip()
    if vid.startswith("UC") or "/channel/" in url:
        return None
    if _is_video_id(vid):
        return f"https://www.youtube.com/watch?v={vid}"
    match = _VIDEO_ID_RE.search(url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    if "/watch" in url:
        return url.split("&")[0]
    return None


def _has_playable_formats(info: dict[str, Any] | None) -> bool:
    if not info:
        return False
    if info.get("url"):
        return True
    for fmt in info.get("formats") or []:
        if fmt.get("url") and fmt.get("acodec") not in (None, "none"):
            return True
    return bool(info.get("formats"))


def _friendly_ytdlp_error(exc: BaseException) -> str:
    msg = str(exc)
    if "confirm your age" in msg.lower():
        return (
            "YouTube age-restricted video — export cookies to a file and set "
            "Settings → Discord → YouTube cookies file, or try a different song."
        )
    if "no video formats found" in msg.lower():
        return "YouTube returned no audio formats for that video — try another result."
    return msg.split("\n", 1)[0][:240]


def _resolve_youtube_track(query: str) -> tuple[str, str]:
    import yt_dlp

    raw = _normalize_query(query)
    is_url = bool(re.match(r"^https?://", raw, re.I))
    search_target = raw if is_url else f"ytsearch{_SEARCH_RESULTS}:{raw}"

    flat_opts = _base_ytdlp_opts(flat=not is_url)
    probe_opts = _base_ytdlp_opts()
    probe_opts["ignoreerrors"] = True

    errors: list[str] = []
    try:
        with yt_dlp.YoutubeDL(flat_opts) as ydl:
            info = ydl.extract_info(search_target, download=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(_friendly_ytdlp_error(exc)) from exc

    if info is None:
        raise ValueError("Could not resolve that YouTube query")

    if is_url:
        candidates = [info]
    else:
        candidates = [e for e in (info.get("entries") or []) if e]

    for entry in candidates:
        play_target = _entry_video_url(entry) if not is_url else (
            entry.get("webpage_url") or entry.get("original_url") or raw
        )
        if not play_target:
            continue
        title = str(entry.get("title") or "Unknown track")
        try:
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                full = ydl.extract_info(play_target, download=False)
            if _has_playable_formats(full):
                resolved_title = str((full or {}).get("title") or title)
                resolved_url = (full or {}).get("webpage_url") or play_target
                log.info("youtube resolved %r -> %s", raw, resolved_title[:60])
                return resolved_url, resolved_title
        except Exception as exc:  # noqa: BLE001
            errors.append(_friendly_ytdlp_error(exc))
            log.debug("skipped youtube candidate %s: %s", play_target, exc)

    detail = errors[0] if errors else "No playable search results"
    raise ValueError(f"No playable YouTube result for {raw!r}. {detail}")


def _make_ytdlp_piped_audio(play_query: str):
    import discord

    stream_args = [
        "-f",
        "bestaudio/best",
        "--no-playlist",
        "--no-warnings",
        "-q",
        *_extractor_args_cli(),
        *_cookie_cli_args(),
        "-o",
        "-",
        play_query,
    ]
    ytdl_proc = subprocess.Popen(
        [sys.executable, "-m", "yt_dlp", *stream_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    stderr_tail: list[str] = []

    def _drain_stderr() -> None:
        proc = ytdl_proc.stderr
        if proc is None:
            return
        try:
            for raw_line in proc:
                line = raw_line.decode(errors="replace").strip()
                if line:
                    stderr_tail.append(line)
                    if len(stderr_tail) > 12:
                        stderr_tail.pop(0)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_drain_stderr, daemon=True, name="ytdlp-stderr").start()

    class _YtdlpPipedAudio(discord.FFmpegPCMAudio):
        def __init__(self) -> None:
            self._ytdl_proc = ytdl_proc
            self._stderr_tail = stderr_tail
            try:
                super().__init__(
                    self._ytdl_proc.stdout,
                    pipe=True,
                    before_options="-nostdin",
                    options="-vn",
                )
            except Exception:
                self._kill_ytdl()
                raise

        def cleanup(self) -> None:
            try:
                super().cleanup()
            finally:
                self._kill_ytdl()

        def _kill_ytdl(self) -> None:
            proc = getattr(self, "_ytdl_proc", None)
            if proc is None:
                return
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                code = proc.returncode
                if code not in (None, 0) and self._stderr_tail:
                    log.error("yt-dlp exited %s: %s", code, self._stderr_tail[-1])
            except Exception:  # noqa: BLE001
                pass
            self._ytdl_proc = None

    return _YtdlpPipedAudio()


def _default_voice_channel() -> str:
    return str(_discord_youtube_settings().get("default_voice_channel") or "").strip()


def patch_discord_manager_playback(manager: Any) -> None:
    """Auto-join default voice channel before YouTube play/queue."""
    if manager is None or getattr(manager, "_unified_youtube_play_patch", False):
        return

    from services.discord.fuzzy_channels import resolve_voice_channel_fuzzy

    async def _ensure_voice():
        voice = manager._sync_active_voice()  # noqa: SLF001
        if voice and voice.is_connected():
            return voice
        channel_name = _default_voice_channel()
        if not channel_name:
            return None
        aliases = _discord_youtube_settings().get("voice_channel_aliases") or {}
        if not isinstance(aliases, dict):
            aliases = {}
        guild = manager._resolve_guild(None)  # noqa: SLF001
        channel = manager._resolve_voice_channel(guild, channel_name)  # noqa: SLF001
        if channel is None:
            channel = resolve_voice_channel_fuzzy(guild, channel_name, aliases)
        if channel is None:
            log.warning("default voice channel not found: %r", channel_name)
            return None
        log.info("auto-joining voice channel %r for youtube", channel.name)
        return await manager._join_voice(channel.name)  # noqa: SLF001

    orig_play = manager._play_youtube  # noqa: SLF001
    orig_queue = manager._queue_youtube  # noqa: SLF001

    async def play_youtube(query: str):
        voice = manager._sync_active_voice()  # noqa: SLF001
        if not voice or not voice.is_connected():
            await _ensure_voice()
        return await orig_play(query)

    async def queue_youtube(query: str):
        voice = manager._sync_active_voice()  # noqa: SLF001
        if not voice or not voice.is_connected():
            await _ensure_voice()
        return await orig_queue(query)

    manager._play_youtube = play_youtube  # noqa: SLF001
    manager._queue_youtube = queue_youtube  # noqa: SLF001
    setattr(manager, "_unified_youtube_play_patch", True)


def patch_youtube_tools() -> None:
    """Replace qwen3 discord_bot YouTube extract/stream helpers."""
    try:
        import tools.discord_bot as discord_bot
    except ImportError:
        log.debug("tools.discord_bot not loaded yet")
        return
    if getattr(discord_bot, _PATCHED, False):
        return

    discord_bot._resolve_youtube_track = _resolve_youtube_track  # noqa: SLF001
    discord_bot._make_ytdlp_piped_audio = _make_ytdlp_piped_audio  # noqa: SLF001
    setattr(discord_bot, _PATCHED, True)
    log.info(
        "youtube patch active (clients=%s, cookies=%s)",
        ",".join(_player_clients()),
        "file" if _cookie_opts().get("cookiefile") else _cookie_opts().get("cookiesfrombrowser", ("none",))[0],
    )
