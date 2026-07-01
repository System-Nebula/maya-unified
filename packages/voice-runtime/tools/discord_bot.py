"""Discord voice tools: connect, join a channel, play YouTube audio.

Runs a discord.py client on a background thread so synchronous tool handlers
can schedule coroutines safely. Requires:

  - Bot token in VA_DISCORD_TOKEN (Bot scope; enable Voice + Connect intents)
  - FFmpeg on PATH (for voice playback)
  - Bot invited to your server with Connect + Speak permissions
  - Read Message History on text channels you want to summarize
  - Message Content intent enabled in the Discord Developer Portal (for reliable reads)
"""

from __future__ import annotations

import asyncio
import difflib
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from config import CONFIG
from observability import get_logger, span

from .registry import ToolSpec

log = get_logger("discord")

FFMPEG_PIPE_BEFORE = "-nostdin"
FFMPEG_OPTS = "-vn"

_YTDLP_EXTRACT_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
}

_YTDLP_STREAM_ARGS = [
    "-f",
    "bestaudio/best",
    "--no-playlist",
    "--no-warnings",
    "-q",
    "--extractor-args",
    "youtube:player_client=android,web",
    "-o",
    "-",
]


def _norm_name(value: str) -> str:
    s = (value or "").strip().lstrip("#").lower()
    s = re.sub(r"[\s_-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _norm_name(value))


_GENERIC_CHANNEL_KEYS = frozenset({
    "chat", "channel", "discord", "text", "the", "voice", "vc", "room",
    "server", "here", "there",
})


def _pick_text_channel(guild, channel_name: str):
    hint = (channel_name or "").strip().lstrip("#")
    if not hint:
        return None
    hint_key = _norm_name_key(hint)
    if hint_key in _GENERIC_CHANNEL_KEYS:
        return None
    target = _norm_name(hint)
    target_key = hint_key
    exact = [
        c for c in guild.text_channels
        if _norm_name(c.name) == target or _norm_name_key(c.name) == target_key
    ]
    if exact:
        return exact[0]
    partial = [
        c for c in guild.text_channels
        if target in _norm_name(c.name) or target_key in _norm_name_key(c.name)
    ]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(c.name for c in partial)
        raise ValueError(f"Ambiguous text channel '{channel_name}'. Matches: {names}")
    names = [c.name for c in guild.text_channels]
    close = difflib.get_close_matches(hint, names, n=1, cutoff=0.55)
    if close:
        for c in guild.text_channels:
            if c.name == close[0]:
                return c
    best = None
    best_ratio = 0.0
    for c in guild.text_channels:
        ratio = difflib.SequenceMatcher(
            None, target_key, _norm_name_key(c.name),
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = c
    if best is not None and best_ratio >= 0.62:
        log.info("fuzzy channel %r -> #%s", channel_name, best.name)
        return best
    return None


def _sanitize_target_user(target_user: str, guild=None) -> str:
    user = (target_user or "").strip()
    m = re.match(r"^(.+?)\s+and\s+(.+)$", user, re.I)
    if not m:
        return user
    name, tail = m.group(1).strip(), m.group(2).strip()
    tail_key = _norm_name_key(tail)
    if tail_key in _GENERIC_CHANNEL_KEYS:
        return name
    if guild is not None and _pick_text_channel(guild, tail) is not None:
        return name
    if len(tail) >= 6 or "-" in tail or "shit" in tail_key:
        return name
    return user


def _user_matches_name(target_user: str, author) -> bool:
    target_user = _sanitize_target_user(target_user)
    target_key = _norm_name_key(target_user)
    if not target_key:
        return False
    candidates = [
        getattr(author, "display_name", "") or "",
        getattr(author, "name", "") or "",
        getattr(author, "global_name", "") or "",
    ]
    for name in candidates:
        key = _norm_name_key(name)
        if not key:
            continue
        if key == target_key or target_key in key or key in target_key:
            return True
        if len(target_key) >= 4 and len(key) >= 4:
            if difflib.SequenceMatcher(None, target_key, key).ratio() >= 0.82:
                return True
    return False


def _recover_channel_hint(channel_hint: str, target_user: str) -> str:
    hint = (channel_hint or "").strip()
    if _norm_name_key(hint) not in _GENERIC_CHANNEL_KEYS:
        return hint
    m = re.match(r"^.+?\s+and\s+(.+)$", (target_user or "").strip(), re.I)
    if m:
        return m.group(1).strip()
    m = re.search(
        r"(shit[\s-]*talk(?:ing)?|sshitposting|[#@]?[\w-]{4,})",
        (target_user or "") + " " + hint,
        re.I,
    )
    if m:
        return m.group(1).lstrip("#@")
    return hint


def _normalize_youtube_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is required")
    if not re.match(r"^https?://", q, re.I):
        q = f"ytsearch1:{q}"
    return q


def _resolve_youtube_track(query: str) -> tuple[str, str]:
    """Resolve a YouTube search/URL to (play_target, title).

    play_target is a stable webpage URL or search string for yt-dlp streaming —
    never a short-lived googlevideo.com URL (FFmpeg gets 403 on those).
    """
    import yt_dlp

    q = _normalize_youtube_query(query)
    with yt_dlp.YoutubeDL(_YTDLP_EXTRACT_OPTS) as ydl:
        info = ydl.extract_info(q, download=False)
    if info is None:
        raise ValueError("Could not resolve that YouTube query")
    if "entries" in info:
        entries = info.get("entries") or []
        if not entries:
            raise ValueError("No YouTube results for that query")
        info = entries[0]
    title = info.get("title") or "Unknown track"
    play_target = info.get("webpage_url") or info.get("original_url")
    if not play_target:
        raw = (query or "").strip()
        play_target = raw if re.match(r"^https?://", raw, re.I) else f"ytsearch1:{raw}"
    return play_target, title


def _make_ytdlp_piped_audio(play_query: str):
    """Return a discord FFmpegPCMAudio fed by yt-dlp stdout."""
    import discord

    ytdl_proc = subprocess.Popen(
        [sys.executable, "-m", "yt_dlp", *_YTDLP_STREAM_ARGS, play_query],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    class _YtdlpPipedAudio(discord.FFmpegPCMAudio):
        def __init__(self) -> None:
            self._ytdl_proc = ytdl_proc
            try:
                super().__init__(
                    self._ytdl_proc.stdout,
                    pipe=True,
                    before_options=FFMPEG_PIPE_BEFORE,
                    options=FFMPEG_OPTS,
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
            except Exception:  # noqa: BLE001
                pass
            self._ytdl_proc = None

    return _YtdlpPipedAudio()


@dataclass
class _QueueItem:
    query: str


IncomingMessageHandler = Callable[[dict[str, Any]], Optional[str]]


class DiscordManager:
    """Thread-hosted discord.py client with voice + YouTube playback."""

    def __init__(
        self,
        token: str,
        default_guild_id: int | None = None,
        music_volume: float = 0.85,
        on_incoming_message: IncomingMessageHandler | None = None,
    ):
        self.token = token.strip()
        self._default_guild_id = int(default_guild_id) if default_guild_id else None
        self._music_volume = max(0.0, min(2.0, float(music_volume)))
        self._on_incoming_message = on_incoming_message
        self._auto_reply_enabled = bool(getattr(CONFIG.discord, "auto_reply", True))
        self._reply_cooldown_sec = 2.5
        self._last_reply_at: dict[int, float] = {}
        self._now_playing: Optional[str] = None
        self._queue: deque[_QueueItem] = deque()
        self._play_generation = 0
        self._queue_halted = False
        self._max_queue = max(1, int(getattr(CONFIG.discord, "queue_max", 30)))
        self._current_play_query: Optional[str] = None
        self._last_playback_error: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._client = None
        self._voice = None
        self._ready = threading.Event()
        self._start_error: Optional[str] = None
        self._lock = threading.Lock()

    # ----- public sync API (tool handlers) ----------------------------------

    def connect(self) -> dict[str, Any]:
        with self._lock:
            return self._ensure_started()

    def join_voice(self, channel_name: str, guild_name: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            return self._run(self._join_voice(channel_name, guild_name))

    def send_channel_message(
        self,
        channel_name: str,
        content: str,
        guild_name: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            return self._run(self._send_channel_message(channel_name, content, guild_name))

    def fetch_channel_messages(
        self,
        channel_name: str,
        limit: int = 30,
        guild_name: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            safe_limit = max(5, min(100, int(limit or 30)))
            return self._run(
                self._fetch_channel_messages(channel_name, safe_limit, guild_name),
                timeout=45.0,
            )

    def find_user_recent_message(
        self,
        channel_name: str,
        target_user: str,
        guild_name: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            return self._run(
                self._find_user_recent_message(channel_name, target_user, guild_name),
                timeout=45.0,
            )

    def reply_to_user(
        self,
        channel_name: str,
        target_user: str,
        content: str,
        guild_name: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            return self._run(
                self._reply_to_user(channel_name, target_user, content, guild_name),
                timeout=45.0,
            )

    def leave_voice(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"left": False, "reason": "not connected"}
            return self._run(self._leave_voice())

    def play_youtube(self, query: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            if not shutil.which("ffmpeg"):
                raise RuntimeError(
                    "FFmpeg not found on PATH — install it and restart the agent "
                    "(https://ffmpeg.org/download.html)"
                )
            return self._run(self._play_youtube(query), timeout=60.0)

    def queue_youtube(self, query: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_started()
            if not shutil.which("ffmpeg"):
                raise RuntimeError(
                    "FFmpeg not found on PATH — install it and restart the agent "
                    "(https://ffmpeg.org/download.html)"
                )
            return self._run(self._queue_youtube(query), timeout=60.0)

    def show_queue(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"now_playing": None, "upcoming": [], "reason": "not connected"}
            return self._run(self._playback_status())

    def playback_status(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"connected": False, "reason": "not connected"}
            return self._run(self._playback_status())

    def resume_playback(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"resumed": False, "reason": "not connected"}
            return self._run(self._resume_playback(), timeout=90.0)

    def stop_music(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"stopped": False, "reason": "not connected"}
            return self._run(self._stop_music())

    def skip_music(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"skipped": False, "reason": "not connected"}
            return self._run(self._skip_music())

    def set_music_volume(self, volume: float) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"volume": self._music_volume, "reason": "not connected"}
            return self._run(self._set_music_volume(volume))

    def get_music_volume(self) -> float:
        return self._music_volume

    def now_playing(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"playing": None, "reason": "not connected"}
            return self._run(self._now_playing_status())

    def status(self) -> dict[str, Any]:
        with self._lock:
            if not self.is_ready():
                return {"connected": False, "reason": self._start_error or "not logged in"}
            return self._run(self._status())

    def close(self) -> None:
        with self._lock:
            if self._loop is None:
                return
            try:
                self._run(self._shutdown(), timeout=12.0)
            except Exception:  # noqa: BLE001
                pass
            self._ready.clear()
            self._loop = None
            self._thread = None

    def is_ready(self) -> bool:
        return self._ready.is_set()

    # ----- thread / asyncio -------------------------------------------------

    def _ensure_started(self, timeout: float = 45.0) -> dict[str, Any]:
        if self.is_ready():
            return self._run(self._status())
        if not self.token:
            raise RuntimeError("VA_DISCORD_TOKEN is not set")
        self._start_error = None
        self._ready.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._thread_main, name="discord-bot", daemon=True)
            self._thread.start()
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError(self._start_error or "Discord login timed out")
        return self._run(self._status())

    def _thread_main(self) -> None:
        import discord

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._client_main())
        except Exception as exc:  # noqa: BLE001
            self._start_error = str(exc)
            log.exception("bot stopped: %s", exc)
        finally:
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass

    async def _client_main(self) -> None:
        import discord

        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True
        intents.message_content = True
        intents.guild_messages = True
        self._client = discord.Client(intents=intents)
        manager = self

        @self._client.event
        async def on_ready() -> None:
            user = self._client.user
            log.info("logged in as %s (%s server(s))", user, len(self._client.guilds))
            self._ready.set()

        @self._client.event
        async def on_message(message) -> None:
            await manager._on_incoming_discord_message(message)

        await self._client.start(self.token)

    def _run(self, coro, timeout: float = 30.0):
        if self._loop is None:
            raise RuntimeError("Discord event loop is not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _shutdown(self) -> None:
        self._queue.clear()
        self._queue_halted = True
        self._play_generation += 1
        if self._voice and self._voice.is_connected():
            if self._voice.is_playing():
                self._voice.stop()
            await self._voice.disconnect(force=True)
        self._voice = None
        if self._client:
            await self._client.close()

    # ----- discord coroutines -----------------------------------------------

    async def _status(self) -> dict[str, Any]:
        voice = self._sync_active_voice()
        guilds = []
        for g in self._client.guilds:
            channels = [c.name for c in g.voice_channels]
            text_channels = [c.name for c in g.text_channels]
            guilds.append({
                "name": g.name,
                "id": g.id,
                "voice_channels": channels,
                "text_channels": text_channels,
            })
        voice_info = None
        if voice and voice.is_connected() and voice.channel:
            ch = voice.channel
            voice_info = {
                "channel": ch.name,
                "guild": ch.guild.name,
                "playing": voice.is_playing(),
                "paused": voice.is_paused(),
                "now_playing": self._now_playing,
                "volume_percent": int(round(self._music_volume * 100)),
                "queue_length": len(self._queue),
                "queue": [item.query for item in list(self._queue)[:5]],
            }
        return {
            "connected": True,
            "bot": str(self._client.user),
            "guilds": guilds,
            "voice": voice_info,
            "music_volume": self._music_volume,
        }

    def _sync_active_voice(self):
        """Return the live VoiceClient (guild may own it, not our cached ref)."""
        if self._client is None:
            return None
        if self._default_guild_id:
            guild = self._client.get_guild(self._default_guild_id)
            if guild and guild.voice_client and guild.voice_client.is_connected():
                self._voice = guild.voice_client
                return guild.voice_client
        for guild in self._client.guilds:
            vc = guild.voice_client
            if vc and vc.is_connected():
                self._voice = vc
                return vc
        if self._voice and self._voice.is_connected():
            return self._voice
        return None

    def _force_stop_playback(self, voice) -> bool:
        """Stop FFmpeg/discord playback even if is_playing() is wrong."""
        was_active = bool(voice.is_playing() or voice.is_paused())
        src = getattr(voice, "source", None)
        try:
            if voice.is_playing() or voice.is_paused():
                voice.stop()
            elif src is not None:
                src.cleanup()
            else:
                voice.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("stop error: %s", exc)
        if src is not None:
            try:
                src.cleanup()
            except Exception:  # noqa: BLE001
                pass
        return was_active

    def _wrap_audio_source(self, play_query: str):
        import discord

        raw = _make_ytdlp_piped_audio(play_query)
        return discord.PCMVolumeTransformer(raw, volume=self._music_volume)

    def _invalidate_playback(self) -> None:
        """Bump generation so stale voice.play after-callbacks are ignored."""
        self._play_generation += 1

    def _make_after(self, generation: int):
        def _after(error: Optional[Exception]) -> None:
            if error:
                self._last_playback_error = str(error)
                log.error("playback error: %s", error)
            if generation != self._play_generation:
                return
            if self._loop is None:
                return
            asyncio.run_coroutine_threadsafe(self._on_track_finished(), self._loop)

        return _after

    def _voice_is_audible(self, voice) -> bool:
        return bool(voice and (voice.is_playing() or voice.is_paused()))

    async def _playback_status(self) -> dict[str, Any]:
        voice = self._sync_active_voice()
        connected = bool(voice and voice.is_connected())
        audible = self._voice_is_audible(voice)
        upcoming = [item.query for item in self._queue]
        stalled = bool(connected and self._now_playing and not audible)
        idle_with_queue = bool(connected and not self._now_playing and self._queue and not audible)
        return {
            "connected": connected,
            "now_playing": self._now_playing,
            "discord_is_playing": bool(voice and voice.is_playing()),
            "discord_is_paused": bool(voice and voice.is_paused()),
            "upcoming": upcoming,
            "queue_length": len(self._queue),
            "stalled": stalled,
            "idle_with_queue": idle_with_queue,
            "last_error": self._last_playback_error,
            "queue_halted": self._queue_halted,
        }

    async def _resume_playback(self) -> dict[str, Any]:
        voice = self._sync_active_voice()
        if not voice or not voice.is_connected():
            return {"resumed": False, "reason": "not in voice"}
        if self._queue_halted:
            return {"resumed": False, "reason": "queue halted after stop"}
        if self._voice_is_audible(voice):
            return {
                "resumed": False,
                "reason": "already playing",
                "now_playing": self._now_playing,
            }
        self._queue_halted = False
        self._invalidate_playback()
        self._force_stop_playback(voice)
        if self._now_playing and self._current_play_query:
            try:
                await self._start_track(voice, self._current_play_query, self._now_playing)
                return {"resumed": True, "now_playing": self._now_playing, "action": "restarted"}
            except Exception as exc:  # noqa: BLE001
                self._last_playback_error = str(exc)
                log.warning("resume restart failed: %s", exc)
                self._now_playing = None
                self._current_play_query = None
        if self._queue:
            nxt = await self._play_next_from_queue(voice)
            if nxt:
                return {"resumed": True, "now_playing": nxt.get("playing"), "action": "queued_next"}
        return {
            "resumed": False,
            "reason": "nothing to resume",
            "last_error": self._last_playback_error,
        }

    async def _on_track_finished(self) -> None:
        if self._queue_halted:
            self._now_playing = None
            return
        voice = self._sync_active_voice()
        if not voice or not voice.is_connected():
            self._now_playing = None
            return
        if self._queue:
            await self._play_next_from_queue(voice)
        else:
            self._now_playing = None
            log.info("queue finished")

    async def _start_track(self, voice, play_query: str, title: str) -> None:
        generation = self._play_generation
        self._current_play_query = play_query
        self._last_playback_error = None
        source = self._wrap_audio_source(play_query)
        voice.play(source, after=self._make_after(generation))
        self._now_playing = title

    async def _play_next_from_queue(self, voice) -> Optional[dict[str, Any]]:
        while self._queue:
            item = self._queue.popleft()
            try:
                loop = asyncio.get_event_loop()
                play_query, title = await loop.run_in_executor(
                    None, _resolve_youtube_track, item.query,
                )
                await self._start_track(voice, play_query, title)
                ch = voice.channel.name if voice.channel else "?"
                log.info("playing from queue: %s", title)
                return {
                    "playing": title,
                    "channel": ch,
                    "query": item.query,
                    "from_queue": True,
                    "queue_remaining": len(self._queue),
                }
            except Exception as exc:  # noqa: BLE001
                log.warning("skipped bad queue item %r: %s", item.query, exc)
        self._now_playing = None
        return None

    def _resolve_guild(self, guild_name: str | None):
        guilds = list(self._client.guilds)
        if not guilds:
            raise ValueError("Bot is not in any Discord servers")
        if guild_name:
            target = _norm_name(guild_name)
            for g in guilds:
                if _norm_name(g.name) == target or target in _norm_name(g.name):
                    return g
            names = ", ".join(g.name for g in guilds)
            raise ValueError(f"Server '{guild_name}' not found. Bot is in: {names}")
        if self._default_guild_id:
            for g in guilds:
                if g.id == self._default_guild_id:
                    return g
        if len(guilds) == 1:
            return guilds[0]
        names = ", ".join(g.name for g in guilds)
        raise ValueError(
            f"Bot is in multiple servers ({names}). Pass guild_name to pick one."
        )

    def _resolve_voice_channel(self, guild, channel_name: str):
        target = _norm_name(channel_name)
        exact = [c for c in guild.voice_channels if _norm_name(c.name) == target]
        if exact:
            return exact[0]
        partial = [c for c in guild.voice_channels if target in _norm_name(c.name)]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            names = ", ".join(c.name for c in partial)
            raise ValueError(f"Ambiguous channel '{channel_name}'. Matches: {names}")
        return None

    def _resolve_text_channel(self, guild, channel_name: str):
        return _pick_text_channel(guild, str(channel_name))

    def resolve_text_channel_name(
        self,
        channel_hint: str,
        guild_name: str | None = None,
    ) -> str:
        with self._lock:
            self._ensure_started()
            return self._run(
                self._resolve_text_channel_name(channel_hint, guild_name),
            )

    async def _resolve_text_channel_name(
        self,
        channel_hint: str,
        guild_name: str | None,
    ) -> str:
        guild = self._resolve_guild(guild_name)
        channel = _pick_text_channel(guild, str(channel_hint))
        if channel is None:
            names = ", ".join(c.name for c in guild.text_channels) or "(none)"
            raise ValueError(
                f"Text channel '{channel_hint}' not found in {guild.name}. "
                f"Available: {names}"
            )
        return channel.name

    async def _send_channel_message(
        self,
        channel_name: str,
        content: str,
        guild_name: str | None,
    ) -> dict[str, Any]:
        if not channel_name or not str(channel_name).strip():
            raise ValueError("channel_name is required")
        guild = self._resolve_guild(guild_name)
        channel = self._resolve_text_channel(guild, str(channel_name))
        if channel is None:
            names = ", ".join(c.name for c in guild.text_channels) or "(none)"
            raise ValueError(
                f"Text channel '{channel_name}' not found in {guild.name}. "
                f"Available: {names}"
            )
        text = (content or "").strip()
        if not text:
            raise ValueError("message content is required")
        if len(text) > 2000:
            text = text[:1997] + "..."
        msg = await channel.send(text)
        log.info("sent message to #%s (%s chars)", channel.name, len(text))
        return {
            "sent": True,
            "channel": channel.name,
            "guild": guild.name,
            "message_id": msg.id,
            "content": text,
        }

    @staticmethod
    def _message_snippet(msg) -> str:
        parts: list[str] = []
        content = (msg.content or "").strip()
        if content:
            parts.append(content)
        for emb in msg.embeds or []:
            bit = (emb.title or emb.description or "").strip()
            if bit:
                parts.append(f"[embed: {bit[:240]}]")
        if msg.attachments:
            names = ", ".join(a.filename for a in msg.attachments[:3])
            extra = len(msg.attachments) - 3
            if extra > 0:
                names = f"{names}, +{extra} more"
            parts.append(f"[attachment: {names}]")
        return " ".join(parts) or "(no text)"

    def _user_matches(self, target_user: str, author) -> bool:
        return _user_matches_name(target_user, author)

    async def _on_incoming_discord_message(self, message) -> None:
        if not self._auto_reply_enabled or not self._on_incoming_message:
            return
        if message.author.bot or not message.guild:
            return
        if self._default_guild_id and message.guild.id != self._default_guild_id:
            return
        trigger = await self._incoming_message_trigger(message)
        if trigger is None:
            return
        now = time.monotonic()
        ch_id = message.channel.id
        if now - self._last_reply_at.get(ch_id, 0) < self._reply_cooldown_sec:
            return
        try:
            context = await self._build_incoming_message_context(message, trigger)
            loop = asyncio.get_event_loop()
            reply_text = await loop.run_in_executor(
                None, lambda: self._on_incoming_message(context),
            )
            text = (reply_text or "").strip()
            if not text:
                return
            if len(text) > 2000:
                text = text[:1997] + "..."
            await message.reply(text, mention_author=True)
            self._last_reply_at[ch_id] = now
            log.info("auto-replied in #%s to %s", message.channel.name, message.author)
        except Exception as exc:  # noqa: BLE001
            log.warning("discord auto-reply failed: %s", exc)

    async def _incoming_message_trigger(self, message) -> Optional[str]:
        import discord

        me = self._client.user
        if me and me in message.mentions:
            return "mention"
        ref = message.reference
        if not ref or not ref.message_id:
            return None
        parent = ref.resolved
        if parent is None:
            try:
                parent = await message.channel.fetch_message(ref.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        if parent.author.id == me.id:
            return "reply"
        return None

    async def _build_incoming_message_context(self, message, trigger: str) -> dict[str, Any]:
        recent: list[dict[str, Any]] = []
        async for msg in message.channel.history(limit=12, before=message.created_at):
            recent.append({
                "author": getattr(msg.author, "display_name", str(msg.author)),
                "content": self._message_snippet(msg),
            })
        recent.reverse()
        return {
            "trigger": trigger,
            "channel": message.channel.name,
            "guild": message.guild.name if message.guild else None,
            "guild_id": message.guild.id if message.guild else None,
            "author": message.author.display_name,
            "author_id": message.author.id,
            "content": self._message_snippet(message),
            "message_id": message.id,
            "recent_messages": recent,
        }

    async def _find_user_recent_message(
        self,
        channel_name: str,
        target_user: str,
        guild_name: str | None,
    ) -> dict[str, Any]:
        if not target_user or not str(target_user).strip():
            raise ValueError("target_user is required")
        guild = self._resolve_guild(guild_name)
        raw_user = str(target_user).strip()
        channel_hint = _recover_channel_hint(str(channel_name), raw_user)
        channel = _pick_text_channel(guild, channel_hint)
        target_user = _sanitize_target_user(raw_user, guild)
        if channel is None:
            names = ", ".join(c.name for c in guild.text_channels) or "(none)"
            raise ValueError(
                f"Text channel '{channel_name}' not found in {guild.name}. "
                f"Available: {names}"
            )
        match = None
        async for msg in channel.history(limit=80):
            if msg.author.bot:
                continue
            if self._user_matches(target_user, msg.author):
                match = msg
                break
        if match is None:
            raise ValueError(
                f"No recent message from '{target_user}' in #{channel.name}."
            )
        return {
            "channel": channel.name,
            "guild": guild.name,
            "target_user": match.author.display_name,
            "message_id": match.id,
            "content": self._message_snippet(match),
            "timestamp": match.created_at.isoformat() if match.created_at else None,
        }

    async def _reply_to_user(
        self,
        channel_name: str,
        target_user: str,
        content: str,
        guild_name: str | None,
    ) -> dict[str, Any]:
        import discord

        text = (content or "").strip()
        if not text:
            raise ValueError("message content is required")
        if len(text) > 2000:
            text = text[:1997] + "..."
        info = await self._find_user_recent_message(channel_name, target_user, guild_name)
        guild = self._resolve_guild(guild_name)
        channel = self._resolve_text_channel(guild, info["channel"])
        if channel is None:
            raise ValueError(f"Channel '{channel_name}' not found")
        try:
            ref_msg = await channel.fetch_message(int(info["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            raise ValueError(f"Couldn't load message to reply to: {exc}") from exc
        msg = await ref_msg.reply(text, mention_author=True)
        log.info("replied to %s in #%s", info["target_user"], channel.name)
        return {
            "sent": True,
            "channel": channel.name,
            "guild": guild.name,
            "target_user": info["target_user"],
            "reply_to_message_id": info["message_id"],
            "message_id": msg.id,
            "content": text,
        }

    async def _fetch_channel_messages(
        self,
        channel_name: str,
        limit: int,
        guild_name: str | None,
    ) -> dict[str, Any]:
        import discord

        if not channel_name or not str(channel_name).strip():
            raise ValueError("channel_name is required")
        guild = self._resolve_guild(guild_name)
        channel = self._resolve_text_channel(guild, str(channel_name))
        if channel is None:
            names = ", ".join(c.name for c in guild.text_channels) or "(none)"
            raise ValueError(
                f"Text channel '{channel_name}' not found in {guild.name}. "
                f"Available: {names}"
            )
        try:
            raw: list = []
            async for msg in channel.history(limit=limit):
                raw.append(msg)
        except discord.Forbidden as exc:
            raise ValueError(
                f"Can't read #{channel.name} — bot needs Read Message History permission."
            ) from exc
        raw.reverse()
        messages: list[dict[str, Any]] = []
        for msg in raw:
            text = self._message_snippet(msg)
            if text == "(no text)" and msg.system_content:
                text = msg.system_content
            messages.append({
                "author": getattr(msg.author, "display_name", str(msg.author)),
                "content": text,
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
            })
        log.info("fetched %s message(s) from #%s", len(messages), channel.name)
        return {
            "channel": channel.name,
            "guild": guild.name,
            "count": len(messages),
            "messages": messages,
        }

    async def _join_voice(self, channel_name: str, guild_name: str | None) -> dict[str, Any]:
        import discord

        if not channel_name or not str(channel_name).strip():
            raise ValueError("channel_name is required")
        guild = self._resolve_guild(guild_name)
        channel = self._resolve_voice_channel(guild, str(channel_name))
        if channel is None:
            names = ", ".join(c.name for c in guild.voice_channels) or "(none)"
            raise ValueError(
                f"Voice channel '{channel_name}' not found in {guild.name}. "
                f"Available: {names}"
            )

        if self._voice and self._voice.is_connected():
            if self._voice.channel and self._voice.channel.id == channel.id:
                return {
                    "joined": channel.name,
                    "guild": guild.name,
                    "already": True,
                }
            await self._voice.move_to(channel)
        else:
            self._voice = await channel.connect(reconnect=True, timeout=30.0)

        self._voice = self._sync_active_voice() or self._voice
        return {"joined": channel.name, "guild": guild.name}

    async def _leave_voice(self) -> dict[str, Any]:
        voice = self._sync_active_voice()
        if not voice or not voice.is_connected():
            return {"left": False, "reason": "not in a voice channel"}
        self._queue.clear()
        self._queue_halted = True
        self._invalidate_playback()
        self._force_stop_playback(voice)
        ch = voice.channel.name if voice.channel else None
        await voice.disconnect(force=True)
        self._voice = None
        self._now_playing = None
        return {"left": True, "channel": ch}

    async def _play_youtube(self, query: str) -> dict[str, Any]:
        voice = self._sync_active_voice()
        if not voice or not voice.is_connected():
            raise RuntimeError(
                "Not in a voice channel — call discord_join_voice first with the channel name."
            )
        self._queue.clear()
        self._queue_halted = False
        self._invalidate_playback()
        loop = asyncio.get_event_loop()
        play_query, title = await loop.run_in_executor(None, _resolve_youtube_track, query)
        self._force_stop_playback(voice)
        with span("discord.play", query=query, title=title):
            await self._start_track(voice, play_query, title)
        ch = voice.channel.name if voice.channel else "?"
        log.info("playing: %s (vol %s%%)", title, int(self._music_volume * 100))
        return {
            "playing": title,
            "channel": ch,
            "query": query,
            "volume_percent": int(round(self._music_volume * 100)),
            "queue_cleared": True,
        }

    async def _queue_youtube(self, query: str) -> dict[str, Any]:
        voice = self._sync_active_voice()
        if not voice or not voice.is_connected():
            raise RuntimeError(
                "Not in a voice channel — call discord_join_voice first with the channel name."
            )
        q = (query or "").strip()
        if not q:
            raise ValueError("query is required")
        if len(self._queue) >= self._max_queue:
            raise ValueError(f"Queue is full ({self._max_queue} songs max).")
        self._queue.append(_QueueItem(query=q))
        position = len(self._queue)
        active = bool(
            self._now_playing
            or (voice.is_playing() or voice.is_paused())
        )
        if active:
            log.info("queued #%s: %s", position, q)
            return {
                "queued": q,
                "position": position,
                "now_playing": self._now_playing,
                "queue_length": position,
            }
        self._queue_halted = False
        self._invalidate_playback()
        result = await self._play_next_from_queue(voice)
        if result:
            result["queued_then_played"] = True
            return result
        return {"queued": q, "position": position}

    async def _show_queue(self) -> dict[str, Any]:
        return await self._playback_status()

    async def _stop_music(self) -> dict[str, Any]:
        voice = self._sync_active_voice()
        if not voice or not voice.is_connected():
            return {"stopped": False, "reason": "not in voice"}
        cleared = len(self._queue)
        self._queue.clear()
        self._queue_halted = True
        self._invalidate_playback()
        was_active = self._force_stop_playback(voice)
        skipped = self._now_playing
        self._now_playing = None
        self._current_play_query = None
        log.info("stop_music was_active=%s cleared=%s", was_active, cleared)
        return {
            "stopped": True,
            "was_playing": was_active,
            "track": skipped,
            "queue_cleared": cleared,
        }

    async def _skip_music(self) -> dict[str, Any]:
        voice = self._sync_active_voice()
        if not voice or not voice.is_connected():
            return {"skipped": False, "reason": "not in voice"}
        was = self._now_playing
        had_activity = bool(
            was or voice.is_playing() or voice.is_paused() or self._queue
        )
        if not had_activity:
            return {"skipped": False, "reason": "nothing playing or queued"}
        self._invalidate_playback()
        self._force_stop_playback(voice)
        self._now_playing = None
        if self._queue_halted:
            return {"skipped": True, "track": was, "queue_empty": True}
        if self._queue:
            nxt = await self._play_next_from_queue(voice)
            if nxt:
                log.info("skip_music -> now %s", nxt.get("playing"))
                return {
                    "skipped": True,
                    "track": was,
                    "now_playing": nxt.get("playing"),
                    "queue_remaining": nxt.get("queue_remaining", len(self._queue)),
                }
            if self._queue:
                return {
                    "skipped": True,
                    "track": was,
                    "now_playing": None,
                    "queue_remaining": len(self._queue),
                    "error": self._last_playback_error or "next track failed to start",
                }
        log.info("skip_music was=%s queue_empty", was)
        return {"skipped": True, "track": was, "queue_empty": True}

    async def _set_music_volume(self, volume: float) -> dict[str, Any]:
        self._music_volume = max(0.0, min(2.0, float(volume)))
        voice = self._sync_active_voice()
        if voice and voice.source is not None:
            import discord

            if isinstance(voice.source, discord.PCMVolumeTransformer):
                voice.source.volume = self._music_volume
        pct = int(round(self._music_volume * 100))
        log.info("music volume -> %s%%", pct)
        return {"volume": self._music_volume, "percent": pct}

    async def _now_playing_status(self) -> dict[str, Any]:
        voice = self._sync_active_voice()
        playing = bool(voice and voice.is_playing() and self._now_playing)
        return {
            "playing": self._now_playing if playing else None,
            "is_active": playing,
            "volume_percent": int(round(self._music_volume * 100)),
            "queue_length": len(self._queue),
            "upcoming": [item.query for item in list(self._queue)[:5]],
        }


def build_discord_tools(manager: DiscordManager) -> list[ToolSpec]:
    """Register Discord tools on the shared registry."""

    def _wrap(fn: Callable[..., dict]) -> Callable[[dict], Any]:
        def handler(args: dict) -> Any:
            return fn(**{k: v for k, v in args.items() if v is not None})

        return handler

    return [
        ToolSpec(
            name="discord_connect",
            description=(
                "Log the Discord bot into Discord and list servers/voice channels. "
                "Call this before joining voice if unsure the bot is online."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: manager.connect(),
            group="discord",
        ),
        ToolSpec(
            name="discord_join_voice",
            description=(
                "Join a Discord voice channel by name so the bot can play audio there. "
                "Use the exact channel name the user asks for (e.g. General, Music, VC)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel_name": {
                        "type": "string",
                        "description": "Voice channel name to join (without #).",
                    },
                    "guild_name": {
                        "type": "string",
                        "description": "Discord server name if the bot is in more than one.",
                    },
                },
                "required": ["channel_name"],
            },
            handler=_wrap(lambda channel_name, guild_name=None: manager.join_voice(channel_name, guild_name)),
            group="discord",
        ),
        ToolSpec(
            name="discord_send_message",
            description=(
                "Post a text message in a Discord text channel by channel name. "
                "Use when the user asks to write, post, say, or type something in a "
                "channel (e.g. a joke in #general). Compose the full message body first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel_name": {
                        "type": "string",
                        "description": "Text channel name (without #).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full message text to post (max 2000 chars).",
                    },
                    "guild_name": {
                        "type": "string",
                        "description": "Discord server name if the bot is in more than one.",
                    },
                },
                "required": ["channel_name", "content"],
            },
            handler=_wrap(
                lambda channel_name, content, guild_name=None: manager.send_channel_message(
                    channel_name, content, guild_name,
                )
            ),
            group="discord",
        ),
        ToolSpec(
            name="discord_read_channel",
            description=(
                "Fetch recent messages from a Discord text channel by name. "
                "Use when the user asks to read, recap, or summarize what has been "
                "said in a channel. Summarize the returned messages for speech."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel_name": {
                        "type": "string",
                        "description": "Text channel name (without #).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many recent messages to fetch (5–100, default 30).",
                    },
                    "guild_name": {
                        "type": "string",
                        "description": "Discord server name if the bot is in more than one.",
                    },
                },
                "required": ["channel_name"],
            },
            handler=_wrap(
                lambda channel_name, limit=30, guild_name=None: manager.fetch_channel_messages(
                    channel_name, limit=limit, guild_name=guild_name,
                )
            ),
            group="discord",
        ),
        ToolSpec(
            name="discord_reply_to_user",
            description=(
                "Reply to a specific user's latest message in a Discord text channel. "
                "Use when the user asks to respond or reply to someone in a channel. "
                "Compose the full reply text first, then send it as a threaded reply."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "channel_name": {
                        "type": "string",
                        "description": "Text channel name (without #).",
                    },
                    "target_user": {
                        "type": "string",
                        "description": "Display name or username to reply to.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full reply message text.",
                    },
                    "guild_name": {
                        "type": "string",
                        "description": "Discord server name if the bot is in more than one.",
                    },
                },
                "required": ["channel_name", "target_user", "content"],
            },
            handler=_wrap(
                lambda channel_name, target_user, content, guild_name=None: manager.reply_to_user(
                    channel_name, target_user, content, guild_name,
                )
            ),
            group="discord",
        ),
        ToolSpec(
            name="discord_play_youtube",
            description=(
                "Play a YouTube video or search query now in the joined voice channel. "
                "Clears the queue and swaps to this track. Pass a URL or song/search text."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "YouTube URL or search words (e.g. 'lofi hip hop').",
                    },
                },
                "required": ["query"],
            },
            handler=_wrap(lambda query: manager.play_youtube(query)),
            group="discord",
        ),
        ToolSpec(
            name="discord_queue_youtube",
            description=(
                "Add a YouTube URL or search query to the Discord music queue. "
                "If nothing is playing, starts immediately. Use when the user says "
                "'queue this song' or 'add to queue'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "YouTube URL or search words to queue.",
                    },
                },
                "required": ["query"],
            },
            handler=_wrap(lambda query: manager.queue_youtube(query)),
            group="discord",
        ),
        ToolSpec(
            name="discord_show_queue",
            description=(
                "Report Discord playback status: now playing, upcoming queue, and whether "
                "audio stalled. Use when the user asks what's queued, what should be playing, "
                "or why music stopped."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: manager.playback_status(),
            group="discord",
        ),
        ToolSpec(
            name="discord_resume_playback",
            description=(
                "Resume stalled Discord music or play the next queued track when audio "
                "stopped unexpectedly. Use after discord_show_queue shows stalled/idle."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: manager.resume_playback(),
            group="discord",
        ),
        ToolSpec(
            name="discord_stop_music",
            description=(
                "REQUIRED when the user asks to stop, pause, mute, turn off, or silence "
                "music/song/audio in Discord. Clears the entire queue. Always call this "
                "— never claim music stopped without calling it. Stays in the voice channel."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: manager.stop_music(),
            group="discord",
        ),
        ToolSpec(
            name="discord_skip_music",
            description=(
                "Skip the current Discord song and play the next queued track. "
                "Use when the user says skip, next song, or next track."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: manager.skip_music(),
            group="discord",
        ),
        ToolSpec(
            name="discord_set_volume",
            description=(
                "Set Discord music volume. volume is 0.0–2.0 (1.0 = 100%). "
                "Use when the user asks to turn music up/down or set a percentage."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "volume": {
                        "type": "number",
                        "description": "Volume multiplier 0.0–2.0 (1.0 = 100%).",
                    },
                },
                "required": ["volume"],
            },
            handler=_wrap(lambda volume: manager.set_music_volume(volume)),
            group="discord",
        ),
        ToolSpec(
            name="discord_now_playing",
            description="Report what song is currently playing in Discord voice.",
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: manager.now_playing(),
            group="discord",
        ),
        ToolSpec(
            name="discord_leave_voice",
            description="Disconnect the bot from the current Discord voice channel.",
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: manager.leave_voice(),
            group="discord",
        ),
    ]
