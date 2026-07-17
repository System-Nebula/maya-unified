"""Discord voice tools: connect, join a channel, play YouTube audio.

Runs a py-cord (Pycord) client on a background thread so synchronous tool handlers
can schedule coroutines safely. Requires:

  - Bot token in VA_DISCORD_TOKEN (Bot scope; enable Voice + Connect intents)
  - FFmpeg on PATH (for voice playback)
  - Bot invited to your server with Connect + Speak permissions
  - Read Message History on text channels you want to summarize
  - Message Content intent enabled in the Discord Developer Portal (for reliable reads)
  - Optional VC listen/transcribe via Pycord sinks (discord.voice_listen)
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
from typing import Any, Callable, Iterator, Optional

from config import CONFIG
from observability import get_logger, span

from .registry import ToolSpec

log = get_logger("discord")

FFMPEG_PIPE_BEFORE = "-nostdin"

# Mirror local smart-barge filters (avoid importing agent → circular).
_VC_FILLER = {
    "um", "uh", "uhm", "hm", "hmm", "mm", "mmm", "ah", "er", "erm", "huh",
    "oh", "eh", "umm", "uhh", "mhm", "uh-huh",
}
_VC_BARGE_JUNK = {
    "you", "the", "a", "an", "i", "it", "is", "be", "we", "me", "my", "he", "she",
    "beep", "boop", "boom", "bang", "baa", "ba", "la", "ha", "uh", "um", "oh",
    "wow", "huh", "what", "that", "this",
}


_VC_ASR_JUNK = {
    "okay", "ok", "the", "you", "thank you", "thanks", "hmm", "um", "uh", "yeah",
    "yes", "no", "oh", "ah", "bye", "hello", "hi",
}


def _vc_should_accept_transcript(text: str, *, peak_energy: float, duration_sec: float) -> bool:
    """Reject silence hallucinations and weak noise (muted mic / bot bleed)."""
    from config import CONFIG

    min_peak = float(getattr(CONFIG.discord, "vc_min_peak_energy", 350.0) or 350.0)
    if peak_energy < min_peak:
        return False
    if not _vc_meaningful_transcript(text):
        return False
    norm = (text or "").strip().lower().strip(".!?")
    if not norm:
        return False
    words = norm.split()
    if len(words) <= 2 and words[0] in _VC_ASR_JUNK and peak_energy < 900:
        return False
    if duration_sec < 0.45 and len(norm) < 8 and peak_energy < 600:
        return False
    return True


def _vc_meaningful_transcript(text: str) -> bool:
    """True if STT looks like real user speech worth interrupting for."""
    stripped = (text or "").strip()
    if len(stripped) < 2:
        return False
    words = re.findall(r"[a-z']+", stripped.lower())
    if not words or not any(w not in _VC_FILLER for w in words):
        return False
    if len(words) == 1:
        w = words[0]
        if w in _VC_BARGE_JUNK or len(w) <= 3:
            return False
        if len(w) >= 4 and len(set(w)) <= 2:
            return False
    for w in words:
        if len(w) >= 4 and len(set(w)) == 1:
            return False
    if len(words) >= 2 and len(set(words)) == 1:
        return False
    return True


_VC_INCOMPLETE_TAILS = (
    " about",
    " about the",
    " tell me about",
    " tell me",
    " what about",
    " what's",
    " whats",
    " the last",
    " the latest",
    " posted in",
    " posted",
    " the",
    " a",
    " an",
    " in",
    " on",
    " for",
    " to",
    " of",
    " and",
    " or",
    " with",
    " from",
    " last",
    " latest",
)


def _vc_transcript_looks_incomplete(text: str) -> bool:
    """True when STT looks cut off mid-thought (pause before finishing)."""
    raw = (text or "").strip()
    if not raw:
        return False
    if raw.endswith(("-", "…", "...", ",", ";", ":")):
        return True
    bare = raw.rstrip(".!?…").rstrip()
    tl = bare.lower()
    if not tl:
        return True
    if tl in {
        "can you",
        "could you",
        "hey can you",
        "hey could you",
        "tell me about",
        "can you tell me about",
        "could you tell me about",
    }:
        return True
    return any(tl.endswith(tail) for tail in _VC_INCOMPLETE_TAILS)

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


IncomingMessageHandler = Callable[[dict[str, Any]], Optional[str] | tuple[str, Optional[bytes]]]
VoiceClipHandler = Callable[[str, Optional[str]], Optional[bytes]]
VoiceHybridHandler = Callable[[str, Optional[str], str], Optional[bytes]]
VoiceStreamHandler = Callable[[str, Optional[str]], Iterator[bytes]]
# Second tuple element: prebuilt WAV bytes, or str delivery instruct for TTS.
VCUtteranceHandler = Callable[
    [dict[str, Any]],
    Optional[str] | tuple[str, Optional[bytes]] | tuple[str, Optional[str]],
]
# (mono int16 ndarray, sample_rate) -> transcript text
TranscribeHandler = Callable[[Any, int], str]


def _discord_files_from_wav(wav: Optional[bytes]) -> list:
    if not wav:
        return []
    if len(wav) > 8 * 1024 * 1024:
        log.warning("discord voice clip too large (%s bytes) — skipping attach", len(wav))
        return []
    import io

    import discord

    buf = io.BytesIO(wav)
    buf.seek(0)
    return [discord.File(buf, filename="maya-voice.wav")]


class DiscordManager:
    """Thread-hosted py-cord client with voice playback + optional VC listen."""

    def __init__(
        self,
        token: str,
        default_guild_id: int | None = None,
        music_volume: float = 0.85,
        on_incoming_message: IncomingMessageHandler | None = None,
        voice_clip_fn: VoiceClipHandler | None = None,
        voice_hybrid_fn: VoiceHybridHandler | None = None,
        voice_stream_fn: VoiceStreamHandler | None = None,
        on_vc_utterance: VCUtteranceHandler | None = None,
        transcribe_fn: TranscribeHandler | None = None,
    ):
        self.token = token.strip()
        self._default_guild_id = int(default_guild_id) if default_guild_id else None
        self._music_volume = max(0.0, min(2.0, float(music_volume)))
        self._on_incoming_message = on_incoming_message
        self._voice_clip_fn = voice_clip_fn
        self._voice_hybrid_fn = voice_hybrid_fn
        self._voice_stream_fn = voice_stream_fn
        self._on_vc_utterance = on_vc_utterance
        self._transcribe_fn = transcribe_fn
        self._reply_cooldown_sec = 2.5
        self._vc_reply_cooldown_sec = 0.25
        self._last_reply_at: dict[int, float] = {}
        self._last_vc_reply_at: dict[int, float] = {}
        self._vc_payload_q: deque = deque()
        self._vc_drain_scheduled = False
        # author_id -> {"text", "pcm", "sr", "ts"} for mid-sentence STT fragments
        self._vc_incomplete_hold: dict[int, dict[str, Any]] = {}
        self._vc_turn_lock: Optional[asyncio.Lock] = None
        self._vc_reply_gen = 0
        self._vc_speaking = False
        self._vc_ducked = False
        self._vc_pre_duck_volume: float | None = None
        self._vc_reply_task: Optional[asyncio.Task] = None
        self._last_vc_bot_text = ""
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
        self._listen_sink = None
        self._listening = False
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
            # DAVE + channel moves often exceed 30s; allow a clean reconnect cycle.
            return self._run(self._join_voice(channel_name, guild_name), timeout=75.0)

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

    def speak_vc_followup(self, text: str) -> dict[str, Any]:
        """Speak a background companion follow-up into the current voice channel."""
        with self._lock:
            if not self.is_ready():
                return {"ok": False, "reason": "not connected"}
            return self._run(self._speak_vc_followup(text), timeout=120.0)

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
        intents.members = True  # resolve VC speakers for DAVE SSRC mapping
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
        await self._stop_voice_listen()
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
                "listening": self._listening,
            }
        return {
            "connected": True,
            "bot": str(self._client.user),
            "guilds": guilds,
            "voice": voice_info,
            "music_volume": self._music_volume,
            "voice_listen": self._voice_listen_enabled(),
            "listening": self._listening,
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
            url = (getattr(emb, "url", None) or "").strip()
            bit = (emb.title or emb.description or "").strip()
            if url:
                parts.append(url)
            if bit:
                parts.append(f"[embed: {bit[:240]}]")
            # Some clients put the watch link only in author/url fields.
            for attr in ("thumbnail", "video", "author", "provider"):
                obj = getattr(emb, attr, None)
                nested = getattr(obj, "url", None) if obj is not None else None
                if nested and str(nested) not in parts:
                    parts.append(str(nested))
        if msg.attachments:
            names = ", ".join(a.filename for a in msg.attachments[:3])
            extra = len(msg.attachments) - 3
            if extra > 0:
                names = f"{names}, +{extra} more"
            parts.append(f"[attachment: {names}]")
        return " ".join(parts) or "(no text)"

    def _user_matches(self, target_user: str, author) -> bool:
        return _user_matches_name(target_user, author)

    def _attach_voice_enabled(self) -> bool:
        return bool(
            self._voice_clip_fn
            and getattr(CONFIG.discord, "attach_voice", True)
        )

    async def _reply_voice_files(self, text: str) -> list:
        if not self._attach_voice_enabled():
            if getattr(CONFIG.discord, "attach_voice", True) and not self._voice_clip_fn:
                log.warning("discord voice clip skipped — no TTS hook (restart agent)")
            elif not getattr(CONFIG.discord, "attach_voice", True):
                log.debug("discord voice clip skipped — attach_voice off")
            return []
        import asyncio

        loop = asyncio.get_event_loop()
        try:
            wav = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._voice_clip_fn(text, None)),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            log.warning("discord voice clip synthesis timed out")
            return []
        except Exception as exc:  # noqa: BLE001
            log.warning("discord voice clip synthesis failed: %s", exc)
            return []
        files = _discord_files_from_wav(wav)
        if wav and files:
            log.info("discord voice clip ready (%s bytes)", len(wav))
        return files

    @staticmethod
    def _parse_incoming_reply(
        raw,
    ) -> tuple[Optional[str], Optional[bytes], Optional[str]]:
        if raw is None:
            return None, None, None
        if isinstance(raw, tuple) and raw:
            text = str(raw[0] or "").strip()
            second = raw[1] if len(raw) > 1 else None
            if isinstance(second, (bytes, bytearray)):
                return text or None, bytes(second), None
            if isinstance(second, str):
                return text or None, None, second.strip() or None
            return text or None, None, None
        text = str(raw).strip()
        return text or None, None, None

    def _auto_reply_enabled(self) -> bool:
        return bool(getattr(CONFIG.discord, "auto_reply", True))

    async def _on_incoming_discord_message(self, message) -> None:
        if not self._auto_reply_enabled() or not self._on_incoming_message:
            return
        if message.author.bot or not message.guild:
            return
        if self._default_guild_id and message.guild.id != self._default_guild_id:
            log.debug(
                "discord auto-reply skipped guild %s (configured %s)",
                message.guild.id,
                self._default_guild_id,
            )
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
            reply_raw = await loop.run_in_executor(
                None, lambda: self._on_incoming_message(context),
            )
            text, _prebuilt_wav, _instruct = self._parse_incoming_reply(reply_raw)
            if not text:
                return
            if len(text) > 2000:
                text = text[:1997] + "..."
            files = _discord_files_from_wav(_prebuilt_wav) if _prebuilt_wav else []
            if not files and getattr(CONFIG.discord, "attach_voice", True):
                files = await self._reply_voice_files(text)
            await message.reply(text, mention_author=True, files=files or None)
            self._last_reply_at[ch_id] = now
            log.info(
                "auto-replied in #%s to %s%s",
                message.channel.name,
                message.author,
                " (+ voice)" if files else "",
            )
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
        async for msg in message.channel.history(limit=20, before=message.created_at):
            if getattr(msg.author, "bot", False):
                continue
            recent.append({
                "author": getattr(msg.author, "display_name", str(msg.author)),
                "content": self._message_snippet(msg),
            })
            if len(recent) >= 12:
                break
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
        recent: list[dict[str, Any]] = []
        match = None
        async for msg in channel.history(limit=80):
            if msg.author.bot:
                continue
            entry = {
                "author": getattr(msg.author, "display_name", str(msg.author)),
                "content": self._message_snippet(msg),
            }
            if len(recent) < 25:
                recent.append(entry)
            if match is None and self._user_matches(target_user, msg.author):
                match = msg
        recent.reverse()
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
            "recent_messages": recent[-15:],
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
        files = await self._reply_voice_files(text)
        msg = await ref_msg.reply(text, mention_author=True, files=files or None)
        log.info(
            "replied to %s in #%s%s",
            info["target_user"],
            channel.name,
            " (+ voice)" if files else "",
        )
        return {
            "sent": True,
            "channel": channel.name,
            "guild": guild.name,
            "target_user": info["target_user"],
            "reply_to_message_id": info["message_id"],
            "message_id": msg.id,
            "content": text,
            "voice_attached": bool(files),
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

    def _voice_listen_enabled(self) -> bool:
        return bool(getattr(CONFIG.discord, "voice_listen", False))

    async def _wait_recording_stopped(self, voice: Any, *, timeout: float = 2.5) -> bool:
        """Best-effort wait until py-cord clears voice.recording after stop."""
        if voice is None:
            return True
        deadline = time.monotonic() + max(0.25, timeout)
        while time.monotonic() < deadline:
            if not getattr(voice, "recording", False) and not getattr(
                voice, "listening", False
            ):
                return True
            try:
                if getattr(voice, "recording", False) and hasattr(voice, "stop_recording"):
                    voice.stop_recording()
                elif getattr(voice, "listening", False) and hasattr(voice, "stop_listening"):
                    voice.stop_listening()
            except Exception as exc:  # noqa: BLE001
                log.debug("wait_recording_stopped: %s", exc)
            await asyncio.sleep(0.08)
        still = bool(
            getattr(voice, "recording", False) or getattr(voice, "listening", False)
        )
        if still:
            log.warning(
                "voice recording flag still set after stop (recording=%s listening=%s)",
                getattr(voice, "recording", False),
                getattr(voice, "listening", False),
            )
        return not still

    async def _stop_voice_listen(self) -> None:
        voice = self._sync_active_voice()
        sink = self._listen_sink
        self._listen_sink = None
        self._listening = False
        if voice is None:
            if sink is not None:
                try:
                    sink.cleanup()
                except Exception:  # noqa: BLE001
                    pass
            return
        try:
            if getattr(voice, "recording", False) or getattr(voice, "listening", False):
                if hasattr(voice, "stop_recording"):
                    voice.stop_recording()
                elif hasattr(voice, "stop_listening"):
                    voice.stop_listening()
        except Exception as exc:  # noqa: BLE001
            log.debug("stop_recording: %s", exc)
        if sink is not None:
            try:
                sink.cleanup()
            except Exception:  # noqa: BLE001
                pass
        await self._wait_recording_stopped(voice)

    async def _ensure_voice_listen(self) -> bool:
        if not self._voice_listen_enabled():
            return False
        if not self._on_vc_utterance or not self._transcribe_fn:
            log.debug("vc listen skipped — missing utterance/transcribe handlers")
            return False
        voice = self._sync_active_voice()
        if voice is None or not voice.is_connected():
            return False
        if (
            self._listening
            and self._listen_sink is not None
            and getattr(voice, "recording", False)
        ):
            return True
        await self._stop_voice_listen()
        voice = self._sync_active_voice() or voice
        if voice is None or not voice.is_connected():
            return False
        from services.discord.dave_receive_patch import (
            apply_dave_receive_patches,
            reset_recv_stats,
            wait_for_dave_ready,
        )
        from tools.discord_vc_listen import build_utterance_sink

        apply_dave_receive_patches()
        reset_recv_stats()
        await wait_for_dave_ready(voice)

        try:
            from config import CONFIG
            from services.voice.hushmic import get_hushmic_processor

            if CONFIG.audio.hushmic_enabled:
                hm = get_hushmic_processor()
                if hm.ready():
                    log.info("discord vc HushMic enabled model=%s", CONFIG.audio.hushmic_model)
        except Exception as exc:  # noqa: BLE001
            log.debug("discord vc HushMic preload skipped: %s", exc)

        bot_id = self._client.user.id if self._client and self._client.user else None

        def _on_raw(payload: dict[str, Any]) -> None:
            if self._loop is None:
                return
            asyncio.run_coroutine_threadsafe(self._handle_vc_utterance(payload), self._loop)

        def _bot_speaking() -> bool:
            if self._vc_speaking:
                return True
            v = self._sync_active_voice()
            return bool(v and v.is_playing() and not self._now_playing)

        sink = build_utterance_sink(
            on_utterance=_on_raw,
            bot_user_id=bot_id,
            voice_client=voice,
            silence_ms=float(
                getattr(CONFIG.discord, "vc_silence_ms", None) or CONFIG.vad.silence_ms
            ),
            min_ms=float(CONFIG.vad.min_speech_ms),
            merge_ms=float(CONFIG.discord.vc_merge_ms),
            energy_threshold=float(CONFIG.discord.vc_energy_threshold),
            min_peak_energy=float(CONFIG.discord.vc_min_peak_energy),
            barge_onset_ms=float(CONFIG.discord.vc_barge_onset_ms),
            bot_speaking_fn=_bot_speaking,
            on_barge_onset=self._vc_barge_onset,
        )
        ch = voice.channel
        sink.set_channel_meta(
            channel_name=ch.name if ch else "",
            guild_name=ch.guild.name if ch and ch.guild else "",
            guild_id=ch.guild.id if ch and ch.guild else None,
        )

        def _finished(error: Exception | None = None) -> None:
            if error:
                log.warning("discord vc listen stopped with error: %s", error)
            else:
                log.info("discord vc listen finished")
            self._listening = False
            # py-cord often ends the recorder when playback is interrupted / DAVE
            # glitches. Restart listen while we remain in the voice channel.
            if self._loop is None or not self._voice_listen_enabled():
                return

            async def _restart_listen() -> None:
                await asyncio.sleep(0.2)
                voice = self._sync_active_voice()
                if voice is None or not voice.is_connected():
                    return
                if self._listening and self._listen_sink is not None and getattr(
                    voice, "recording", False
                ):
                    return
                ok = await self._ensure_voice_listen()
                if ok:
                    log.info("discord vc listen restarted after recorder stop")
                else:
                    log.warning("discord vc listen failed to restart after recorder stop")

            try:
                asyncio.run_coroutine_threadsafe(_restart_listen(), self._loop)
            except Exception as exc:  # noqa: BLE001
                log.debug("vc listen restart schedule failed: %s", exc)

        try:
            # py-cord always warns about DAVE; receive may still work with davey.
            import warnings

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Voice reception is currently broken.*",
                    category=RuntimeWarning,
                )
                for attempt in range(2):
                    try:
                        voice.start_recording(sink, _finished)
                        break
                    except Exception as exc:  # noqa: BLE001
                        msg = str(exc).lower()
                        if attempt == 0 and "already recording" in msg:
                            log.warning(
                                "discord vc listen stale recorder — forcing restart (%s)",
                                exc,
                            )
                            await self._stop_voice_listen()
                            voice = self._sync_active_voice() or voice
                            await self._wait_recording_stopped(voice)
                            sink.set_channel_meta(
                                channel_name=ch.name if ch else "",
                                guild_name=ch.guild.name if ch and ch.guild else "",
                                guild_id=ch.guild.id if ch and ch.guild else None,
                            )
                            continue
                        raise
            self._listen_sink = sink
            self._listening = True
            log.info(
                "discord vc listen started in #%s (py-cord receive)",
                ch.name if ch else "?",
            )
            return True
        except Exception as exc:  # noqa: BLE001
            self._listening = False
            self._listen_sink = None
            log.warning("discord vc listen failed to start: %s", exc)
            return False

    def _vc_barge_mode(self) -> str:
        """Discord VC barge policy. ``off`` disables interrupt; else smart/instant."""
        mode = str(getattr(CONFIG.audio, "barge_mode", "smart") or "smart").lower()
        if mode == "off":
            return "off"
        if mode not in ("smart", "instant"):
            return "smart"
        return mode

    def _vc_is_reply_playing(self) -> bool:
        if self._now_playing:
            return False
        voice = self._sync_active_voice()
        if voice is None:
            return False
        return bool(self._vc_speaking or voice.is_playing() or voice.is_paused())

    def _vc_looks_like_bot_echo(self, text: str) -> bool:
        last = (self._last_vc_bot_text or "").lower()
        t = (text or "").lower().strip()
        if not last or len(t) < 4:
            return False
        tw = set(re.findall(r"[a-z']+", t))
        lw = set(re.findall(r"[a-z']+", last))
        if not tw:
            return False
        overlap = len(tw & lw) / float(len(tw))
        return overlap >= 0.72 and len(tw) <= 14

    def _vc_barge_onset(self, user_id: int, energy: float) -> None:
        """React to sustained barge onset while Maya is speaking."""
        if self._vc_barge_mode() == "off":
            return
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._vc_barge_onset_async(user_id, energy),
            self._loop,
        )

    async def _vc_barge_onset_async(self, user_id: int, energy: float) -> None:
        """instant: stop; smart: duck gain until transcript decides stop/restore."""
        mode = self._vc_barge_mode()
        if mode == "off":
            return
        if mode == "instant":
            if self._interrupt_vc_reply("barge-onset"):
                log.info("vc barge interrupt user=%s energy=%.1f mode=instant", user_id, energy)
            return
        if self._duck_vc_reply():
            log.info("vc barge duck user=%s energy=%.1f mode=smart", user_id, energy)

    def _duck_vc_reply(self, factor: float = 0.12) -> bool:
        """Lower reply playback gain without stopping (smart barge)."""
        if self._now_playing:
            return False
        voice = self._sync_active_voice()
        if voice is None:
            return False
        if not (self._vc_speaking or voice.is_playing() or voice.is_paused()):
            return False
        src = getattr(voice, "source", None)
        try:
            import discord as _discord

            if not isinstance(src, _discord.PCMVolumeTransformer):
                return False
            if not self._vc_ducked:
                self._vc_pre_duck_volume = float(src.volume)
            base = (
                self._vc_pre_duck_volume
                if self._vc_pre_duck_volume is not None
                else float(src.volume)
            )
            src.volume = max(0.02, float(base) * float(factor))
            self._vc_ducked = True
            return True
        except Exception:  # noqa: BLE001
            return False

    def _unduck_vc_reply(self) -> None:
        """Restore reply playback gain after a rejected smart barge."""
        if not self._vc_ducked:
            return
        try:
            voice = self._sync_active_voice()
            src = getattr(voice, "source", None) if voice is not None else None
            import discord as _discord

            if (
                isinstance(src, _discord.PCMVolumeTransformer)
                and self._vc_pre_duck_volume is not None
            ):
                src.volume = float(self._vc_pre_duck_volume)
        except Exception:  # noqa: BLE001
            pass
        self._vc_ducked = False
        self._vc_pre_duck_volume = None

    def _cancel_vc_reply_task(self) -> None:
        task = self._vc_reply_task
        if task is not None and not task.done():
            task.cancel()
        self._vc_reply_task = None

    def _spawn_vc_reply_task(self, coro, *, name: str) -> asyncio.Task:
        """One authoritative VC reply task — cancel any prior playback worker."""
        self._cancel_vc_reply_task()
        task = asyncio.create_task(coro, name=name)
        self._vc_reply_task = task

        def _clear(done: asyncio.Task) -> None:
            if self._vc_reply_task is done:
                self._vc_reply_task = None
            try:
                exc = done.exception()
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                return
            if exc is not None:
                log.warning("vc reply task failed: %s", exc)

        task.add_done_callback(_clear)
        return task

    def _begin_vc_reply(self) -> int:
        """Retire in-flight reply work and allocate a generation for this turn.

        Music (``_now_playing``) is never interrupted here — spoken replies
        defer to music in ``_play_wav_bytes``.
        """
        self._cancel_vc_reply_task()
        if self._now_playing:
            self._unduck_vc_reply()
            self._vc_reply_gen += 1
            return self._vc_reply_gen
        if self._vc_is_reply_playing():
            self._interrupt_vc_reply("new-turn")
        else:
            self._unduck_vc_reply()
            self._vc_reply_gen += 1
        return self._vc_reply_gen

    def _vc_gen_alive(self, play_gen: int) -> bool:
        return play_gen == self._vc_reply_gen

    def _interrupt_vc_reply(self, reason: str = "barge-in") -> bool:
        """Stop current spoken VC reply (never music). Returns True if stopped."""
        self._unduck_vc_reply()
        if self._now_playing:
            return False
        voice = self._sync_active_voice()
        if voice is None:
            return False
        if not (self._vc_speaking or voice.is_playing() or voice.is_paused()):
            return False
        self._cancel_vc_reply_task()
        self._vc_reply_gen += 1
        self._vc_speaking = False
        self._force_stop_playback(voice)
        log.info("vc reply interrupted (%s)", reason)
        # Ensure mic listen survives playback interrupt (py-cord/DAVE can drop it).
        if self._loop is not None and self._voice_listen_enabled():

            async def _rearm() -> None:
                await asyncio.sleep(0.05)
                if not self._listening or self._listen_sink is None:
                    await self._ensure_voice_listen()

            try:
                asyncio.run_coroutine_threadsafe(_rearm(), self._loop)
            except Exception:  # noqa: BLE001
                pass
        return True

    async def _handle_vc_utterance(self, payload: dict[str, Any]) -> None:
        if not self._voice_listen_enabled() or not self._on_vc_utterance:
            return
        self._vc_payload_q.append(payload)
        if self._loop is None:
            return
        if self._vc_drain_scheduled:
            return
        self._vc_drain_scheduled = True
        asyncio.run_coroutine_threadsafe(self._drain_vc_utterances(), self._loop)

    async def _drain_vc_utterances(self) -> None:
        """Process VC clips one at a time so compose/TTS are not starved."""
        try:
            if self._vc_turn_lock is None:
                self._vc_turn_lock = asyncio.Lock()
            while self._vc_payload_q:
                payload = self._merge_queued_vc_payloads(self._vc_payload_q.popleft())
                try:
                    await self._process_vc_utterance(payload)
                except Exception as exc:  # noqa: BLE001
                    log.warning("vc utterance failed: %s", exc)
        finally:
            self._vc_drain_scheduled = False
            if self._vc_payload_q and self._loop is not None:
                self._vc_drain_scheduled = True
                self._loop.create_task(self._drain_vc_utterances())

    def _merge_queued_vc_payloads(self, first: dict[str, Any]) -> dict[str, Any]:
        """Concatenate back-to-back clips from the same speaker before STT."""
        import numpy as np

        author_id = int(first.get("author_id") or 0)
        chunks = [first.get("pcm_mono_16k")]
        dur = float(first.get("duration_sec") or 0)
        while self._vc_payload_q:
            nxt = self._vc_payload_q[0]
            if int(nxt.get("author_id") or 0) != author_id:
                break
            nxt_dur = float(nxt.get("duration_sec") or 0)
            if dur + nxt_dur > 12.0:
                break
            if dur >= 2.5 and nxt_dur >= 2.0:
                break
            self._vc_payload_q.popleft()
            chunks.append(nxt.get("pcm_mono_16k"))
            dur += nxt_dur
        valid = [c for c in chunks if c is not None]
        if len(valid) <= 1:
            return first
        merged = dict(first)
        try:
            mono = np.concatenate(
                [np.asarray(c, dtype=np.int16).reshape(-1) for c in valid]
            )
        except Exception:  # noqa: BLE001
            return first
        merged["pcm_mono_16k"] = mono
        merged["duration_sec"] = round(
            float(mono.size) / float(first.get("sample_rate") or 16000), 3
        )
        log.info(
            "vc queue-merge author=%s parts=%s dur=%.2fs",
            author_id,
            len(valid),
            merged["duration_sec"],
        )
        return merged

    async def _process_vc_utterance(self, payload: dict[str, Any]) -> None:
        if not self._voice_listen_enabled() or not self._on_vc_utterance:
            return
        author_id = int(payload.get("author_id") or 0)
        pcm = payload.get("pcm_mono_16k")
        sr = int(payload.get("sample_rate") or 16000)
        if pcm is None or self._transcribe_fn is None:
            return
        loop = asyncio.get_event_loop()
        stt_started = time.monotonic()
        try:
            text = await loop.run_in_executor(
                None, lambda: self._transcribe_fn(pcm, sr),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("vc STT failed: %s", exc)
            return
        asr_ms = (time.monotonic() - stt_started) * 1000.0
        text = (text or "").strip()
        peak = float(payload.get("peak_energy") or 0)
        dur = float(payload.get("duration_sec") or 0)
        if len(text) < 2:
            self._unduck_vc_reply()
            log.info(
                "vc STT empty/short author=%s dur=%s peak=%.1f asr_ms=%.0f text=%r",
                payload.get("author") or author_id,
                payload.get("duration_sec"),
                peak,
                asr_ms,
                text,
            )
            return
        log.info(
            "vc STT author=%s dur=%s peak=%.1f asr_ms=%.0f text=%r",
            payload.get("author") or author_id,
            payload.get("duration_sec"),
            peak,
            asr_ms,
            text[:120],
        )
        if not _vc_should_accept_transcript(text, peak_energy=peak, duration_sec=dur):
            self._unduck_vc_reply()
            log.info(
                "vc STT rejected author=%s peak=%.1f text=%r",
                payload.get("author") or author_id,
                peak,
                text[:80],
            )
            return

        # Stitch a prior incomplete fragment from the same speaker.
        held = self._vc_incomplete_hold.pop(author_id, None)
        if held and (time.monotonic() - float(held.get("ts") or 0)) <= 6.0:
            prefix = str(held.get("text") or "").strip()
            if prefix and not text.lower().startswith(prefix.lower()[:24]):
                stitched = f"{prefix.rstrip('.…,;:')} {text.lstrip()}".strip()
                log.info(
                    "vc STT stitch author=%s %r + %r -> %r",
                    payload.get("author") or author_id,
                    prefix[:80],
                    text[:80],
                    stitched[:120],
                )
                text = stitched
                # Prefer re-STT of concatenated audio when both clips exist.
                prev_pcm = held.get("pcm")
                cur_pcm = payload.get("pcm_mono_16k")
                if prev_pcm is not None and cur_pcm is not None and self._transcribe_fn:
                    try:
                        import numpy as np

                        mono = np.concatenate(
                            [
                                np.asarray(prev_pcm, dtype=np.int16).reshape(-1),
                                np.asarray(cur_pcm, dtype=np.int16).reshape(-1),
                            ]
                        )
                        sr = int(payload.get("sample_rate") or held.get("sr") or 16000)
                        re_text = await loop.run_in_executor(
                            None, lambda: self._transcribe_fn(mono, sr),
                        )
                        re_text = (re_text or "").strip()
                        if len(re_text) >= len(stitched) * 0.5:
                            text = re_text
                            payload = dict(payload)
                            payload["pcm_mono_16k"] = mono
                            payload["duration_sec"] = round(float(mono.size) / float(sr), 3)
                            log.info(
                                "vc STT re-transcribe after stitch author=%s text=%r",
                                payload.get("author") or author_id,
                                text[:120],
                            )
                    except Exception as exc:  # noqa: BLE001
                        log.debug("vc stitch re-STT skipped: %s", exc)

        # Cutoff hold — wait for follow-up audio before committing.
        if _vc_transcript_looks_incomplete(text):
            hold_deadline = time.monotonic() + 2.0
            while time.monotonic() < hold_deadline:
                sink = self._listen_sink
                capturing = False
                if sink is not None and hasattr(sink, "user_capturing"):
                    try:
                        capturing = bool(sink.user_capturing(author_id))
                    except Exception:  # noqa: BLE001
                        capturing = False
                queued = (
                    self._vc_payload_q
                    and int(self._vc_payload_q[0].get("author_id") or 0) == author_id
                )
                if queued:
                    break
                if not capturing:
                    await asyncio.sleep(0.15)
                    continue
                await asyncio.sleep(0.2)
            if self._vc_payload_q and int(self._vc_payload_q[0].get("author_id") or 0) == author_id:
                self._vc_payload_q.appendleft(payload)
                merged = self._merge_queued_vc_payloads(self._vc_payload_q.popleft())
                if float(merged.get("duration_sec") or 0) > float(payload.get("duration_sec") or 0) + 0.15:
                    await self._process_vc_utterance(merged)
                    return
            # Still incomplete and nothing queued — hold for the next flush.
            if _vc_transcript_looks_incomplete(text):
                self._vc_incomplete_hold[author_id] = {
                    "text": text,
                    "pcm": payload.get("pcm_mono_16k"),
                    "sr": int(payload.get("sample_rate") or 16000),
                    "ts": time.monotonic(),
                }
                self._unduck_vc_reply()
                log.info(
                    "vc STT incomplete hold author=%s text=%r",
                    payload.get("author") or author_id,
                    text[:120],
                )
                return

        # Clear any stale incomplete hold once we have a complete transcript.
        self._vc_incomplete_hold.pop(author_id, None)

        barge_mode = self._vc_barge_mode()
        playing = self._vc_is_reply_playing()
        barged = False
        if playing:
            if barge_mode == "off":
                # Half-duplex: ignore user speech until bot finishes.
                log.info("vc speech ignored while speaking (barge_mode=off): %r", text[:80])
                return
            if self._vc_looks_like_bot_echo(text):
                self._unduck_vc_reply()
                log.info("vc barge ignored (bot echo): %r", text[:80])
                return
            if barge_mode == "smart" and not _vc_meaningful_transcript(text):
                self._unduck_vc_reply()
                log.info("vc barge ignored (weak transcript): %r", text[:80])
                return
            if barge_mode == "instant" and not _vc_meaningful_transcript(text) and len(text) < 4:
                self._unduck_vc_reply()
                return
            barged = self._interrupt_vc_reply("barge-in")
            if barged:
                log.info("vc barge-in [%s]: %s", payload.get("author") or author_id, text[:160])

        if not barged:
            wait = self._vc_reply_cooldown_sec - (
                time.monotonic() - self._last_vc_reply_at.get(author_id, 0)
            )
            if wait > 0:
                await asyncio.sleep(wait)

        context = {
            "trigger": "vc_barge" if barged else "vc_speech",
            "channel": payload.get("channel") or "",
            "guild": payload.get("guild"),
            "guild_id": payload.get("guild_id"),
            "author": payload.get("author") or str(author_id),
            "author_id": author_id,
            "content": text,
            "duration_sec": payload.get("duration_sec"),
            "barged": barged,
        }
        log.info(
            "vc transcript [%s]%s: %s",
            context["author"],
            " (barge)" if barged else "",
            text[:160],
        )

        if self._vc_turn_lock is None:
            self._vc_turn_lock = asyncio.Lock()

        async with self._vc_turn_lock:
            # Re-check after waiting — bot may have started speaking since STT.
            if not barged and self._vc_is_reply_playing() and barge_mode != "off":
                if self._vc_looks_like_bot_echo(text):
                    self._unduck_vc_reply()
                    log.info("vc barge ignored under lock (bot echo): %r", text[:80])
                    return
                if barge_mode == "smart" and not _vc_meaningful_transcript(text):
                    self._unduck_vc_reply()
                    log.info("vc barge ignored under lock (weak): %r", text[:80])
                    return
                barged = self._interrupt_vc_reply("barge-in-locked")
                if barged:
                    context["trigger"] = "vc_barge"
                    context["barged"] = True
                    log.info(
                        "vc barge-in [%s]: %s",
                        context["author"],
                        text[:160],
                    )

        log.info("vc compose start [%s]: %s", context["author"], text[:120])
        # Allocate generation before compose so barge/new speech during LLM
        # retires this turn before any TTS/playback starts.
        play_gen = self._begin_vc_reply()
        compose_started = time.monotonic()
        try:
            reply_raw = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._on_vc_utterance(context)),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            log.warning("vc compose timed out [%s]", context["author"])
            return
        if not self._vc_gen_alive(play_gen):
            log.info("vc reply superseded during compose — not playing")
            return
        compose_ms = (time.monotonic() - compose_started) * 1000.0
        reply, prebuilt, instruct = self._parse_incoming_reply(reply_raw)
        if not reply:
            log.info("vc compose empty [%s] ms=%.0f", context["author"], compose_ms)
            return
        log.info("vc compose done [%s] ms=%.0f reply=%s", context["author"], compose_ms, reply[:120])
        self._last_vc_reply_at[author_id] = time.monotonic()
        self._last_vc_bot_text = reply
        if not self._vc_gen_alive(play_gen):
            log.info("vc reply superseded after compose — not playing")
            return

        # Hybrid VC: first sentence fast, remainder as one clip (smooth, low latency).
        if (
            not prebuilt
            and getattr(CONFIG.discord, "attach_voice", True)
            and self._voice_hybrid_fn
        ):
            self._spawn_vc_reply_task(
                self._play_vc_reply_hybrid(reply, instruct, play_gen, context),
                name="discord-vc-reply-hybrid",
            )
            return

        wav = prebuilt
        if (
            not wav
            and getattr(CONFIG.discord, "attach_voice", True)
            and self._voice_clip_fn
        ):
            wav = await loop.run_in_executor(
                None, lambda: self._voice_clip_fn(reply, instruct),
            )
        if not self._vc_gen_alive(play_gen):
            log.info("vc reply superseded after TTS — not playing")
            return

        if wav:
            self._spawn_vc_reply_task(
                self._finish_vc_reply(wav, play_gen, context, reply),
                name="discord-vc-reply-play",
            )
            return

        if (
            getattr(CONFIG.discord, "attach_voice", True)
            and self._voice_stream_fn
        ):
            self._spawn_vc_reply_task(
                self._stream_vc_reply(reply, instruct, play_gen, context),
                name="discord-vc-reply-stream",
            )
            return

        await self._announce_vc_reply(context, reply)

    async def _play_vc_reply_hybrid(
        self,
        reply: str,
        instruct: str | None,
        play_gen: int,
        context: dict[str, Any],
    ) -> None:
        if play_gen != self._vc_reply_gen or not self._voice_hybrid_fn:
            return
        loop = asyncio.get_event_loop()
        played_any = False
        try:
            first = await loop.run_in_executor(
                None,
                lambda: self._voice_hybrid_fn(reply, instruct, part="first"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("vc hybrid first synth failed: %s", exc)
            first = None
        if not self._vc_gen_alive(play_gen):
            return
        if first and await self._play_wav_bytes(first, generation=play_gen):
            played_any = True
        if not self._vc_gen_alive(play_gen):
            return
        try:
            rest = await loop.run_in_executor(
                None,
                lambda: self._voice_hybrid_fn(reply, instruct, part="rest"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("vc hybrid rest synth failed: %s", exc)
            rest = None
        if not self._vc_gen_alive(play_gen):
            return
        if rest and await self._play_wav_bytes(rest, generation=play_gen):
            played_any = True
        if not self._vc_gen_alive(play_gen):
            return
        if played_any:
            log.info("vc reply spoken to %s: %s", context["author"], reply[:120])
        else:
            await self._announce_vc_reply(context, reply)

    async def _stream_vc_reply(
        self,
        reply: str,
        instruct: str | None,
        play_gen: int,
        context: dict[str, Any],
    ) -> None:
        if play_gen != self._vc_reply_gen:
            return
        loop = asyncio.get_event_loop()
        # Bound handoff so a slow player cannot unbounded-buffer TTS PCM.
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=3)

        def _producer() -> None:
            try:
                for chunk in self._voice_stream_fn(reply, instruct):
                    if play_gen != self._vc_reply_gen:
                        break
                    if chunk:
                        fut = asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
                        fut.result(timeout=30.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("vc TTS stream failed: %s", exc)
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=_producer, name="discord-vc-tts-stream", daemon=True).start()
        played_any = False
        while True:
            wav = await q.get()
            if wav is None:
                break
            if play_gen != self._vc_reply_gen:
                log.info("vc reply stream superseded")
                return
            if await self._play_wav_bytes(wav, generation=play_gen):
                played_any = True
        if play_gen != self._vc_reply_gen:
            return
        if played_any:
            log.info("vc reply spoken to %s: %s", context["author"], reply[:120])
        else:
            await self._announce_vc_reply(context, reply)

    async def _finish_vc_reply(
        self,
        wav: bytes,
        play_gen: int,
        context: dict[str, Any],
        reply: str,
    ) -> None:
        if play_gen != self._vc_reply_gen:
            log.info("vc reply superseded before play")
            return
        played = await self._play_wav_bytes(wav, generation=play_gen)
        if play_gen != self._vc_reply_gen:
            return
        if played:
            log.info("vc reply spoken to %s: %s", context["author"], reply[:120])
        else:
            await self._announce_vc_reply(context, reply)

    async def _announce_vc_reply(self, context: dict[str, Any], reply: str) -> None:
        voice = self._sync_active_voice()
        guild = voice.guild if voice else None
        if guild is None and context.get("guild_id") and self._client:
            guild = self._client.get_guild(int(context["guild_id"]))
        if guild is None:
            return
        channel = None
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                channel = ch
                break
        if channel is None:
            return
        author = context.get("author") or "someone"
        body = f"**{author}** (VC): {context.get('content', '')}\n**Maya:** {reply}"
        if len(body) > 1900:
            body = body[:1897] + "..."
        try:
            await channel.send(body)
        except Exception as exc:  # noqa: BLE001
            log.debug("vc text announce failed: %s", exc)

    async def _play_wav_bytes(self, wav: bytes, *, generation: int | None = None) -> bool:
        import tempfile

        import discord

        voice = self._sync_active_voice()
        if voice is None or not voice.is_connected():
            return False
        if generation is not None and generation != self._vc_reply_gen:
            return False
        if voice.is_playing() and self._now_playing:
            # Don't interrupt music with a spoken reply.
            log.info("vc reply deferred — music is playing")
            return False
        if voice.is_playing():
            self._force_stop_playback(voice)
        path = None
        try:
            fd, path = tempfile.mkstemp(suffix=".wav")
            import os

            os.close(fd)
            with open(path, "wb") as fh:
                fh.write(wav)
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(path),
                volume=self._music_volume,
            )
            done = asyncio.Event()

            def _after(err: Optional[Exception]) -> None:
                if err:
                    log.warning("vc reply playback error: %s", err)
                if self._loop:
                    self._loop.call_soon_threadsafe(done.set)

            self._vc_speaking = True
            voice.play(source, after=_after)
            try:
                while not done.is_set():
                    if generation is not None and generation != self._vc_reply_gen:
                        self._force_stop_playback(voice)
                        return False
                    try:
                        await asyncio.wait_for(done.wait(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
            except asyncio.TimeoutError:
                self._force_stop_playback(voice)
                return False
            return generation is None or generation == self._vc_reply_gen
        except Exception as exc:  # noqa: BLE001
            log.warning("vc reply play failed: %s", exc)
            return False
        finally:
            if generation is None or generation == self._vc_reply_gen:
                self._vc_speaking = False
            if path:
                try:
                    import os

                    os.remove(path)
                except OSError:
                    pass

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
                await self._stop_voice_listen()
                await self._ensure_voice_listen()
                return {
                    "joined": channel.name,
                    "guild": guild.name,
                    "already": True,
                    "listening": self._listening,
                    "dave_ready": self._dave_session_ready(),
                }
            # move_to often times out / leaves DAVE half-dead. Prefer hard reconnect.
            await self._stop_voice_listen()
            try:
                await self._voice.disconnect(force=True)
            except Exception as exc:  # noqa: BLE001
                log.debug("voice disconnect before rejoin: %s", exc)
            self._voice = None
            await asyncio.sleep(0.4)

        await self._stop_voice_listen()
        self._voice = await channel.connect(reconnect=True, timeout=45.0)
        self._voice = self._sync_active_voice() or self._voice
        listening = await self._ensure_voice_listen()
        dave_ok = self._dave_session_ready()
        if not dave_ok:
            # One more listen pass — MLS keys sometimes land just after connect.
            await asyncio.sleep(1.5)
            listening = await self._ensure_voice_listen() or listening
            dave_ok = self._dave_session_ready()
        if not dave_ok:
            log.warning(
                "joined #%s but DAVE not ready — VC hear may be silent until rejoin",
                channel.name,
            )
        return {
            "joined": channel.name,
            "guild": guild.name,
            "listening": bool(listening or self._listening),
            "dave_ready": dave_ok,
        }

    def _dave_session_ready(self) -> bool:
        voice = self._sync_active_voice()
        if voice is None:
            return False
        try:
            conn = getattr(voice, "_connection", None)
            dave = getattr(conn, "dave_session", None) if conn else None
            return bool(dave is not None and getattr(dave, "ready", False))
        except Exception:  # noqa: BLE001
            return False

    async def _leave_voice(self) -> dict[str, Any]:
        voice = self._sync_active_voice()
        if not voice or not voice.is_connected():
            return {"left": False, "reason": "not in a voice channel"}
        await self._stop_voice_listen()
        self._queue.clear()
        self._queue_halted = True
        self._invalidate_playback()
        self._force_stop_playback(voice)
        ch = voice.channel.name if voice.channel else None
        await voice.disconnect(force=True)
        self._voice = None
        self._now_playing = None
        return {"left": True, "channel": ch}

    async def _speak_vc_followup(self, text: str) -> dict[str, Any]:
        """TTS + play a companion follow-up while already in VC."""
        reply = (text or "").strip()
        if not reply:
            return {"ok": False, "reason": "empty"}
        if not self._voice_listen_enabled():
            return {"ok": False, "reason": "voice_listen off"}
        voice = self._sync_active_voice()
        if voice is None or not voice.is_connected():
            return {"ok": False, "reason": "not in voice"}
        if not self._voice_clip_fn and not self._voice_hybrid_fn:
            return {"ok": False, "reason": "no tts"}

        context = {
            "trigger": "companion_followup",
            "channel": voice.channel.name if voice.channel else "",
            "guild": voice.guild.name if voice.guild else None,
            "guild_id": voice.guild.id if voice.guild else None,
            "author": "maya",
            "author_id": 0,
            "content": reply,
            "barged": False,
        }
        play_gen = self._begin_vc_reply()
        loop = asyncio.get_event_loop()
        clipped = reply[:800]
        if (
            getattr(CONFIG.discord, "attach_voice", True)
            and self._voice_hybrid_fn
        ):
            self._spawn_vc_reply_task(
                self._play_vc_reply_hybrid(clipped, None, play_gen, context),
                name="discord-vc-followup-hybrid",
            )
            return {"ok": True, "mode": "hybrid", "text": clipped}
        wav = None
        if getattr(CONFIG.discord, "attach_voice", True) and self._voice_clip_fn:
            wav = await loop.run_in_executor(
                None, lambda: self._voice_clip_fn(clipped, None),
            )
        if not self._vc_gen_alive(play_gen):
            return {"ok": False, "reason": "superseded"}
        if wav:
            self._spawn_vc_reply_task(
                self._finish_vc_reply(wav, play_gen, context, clipped),
                name="discord-vc-followup-play",
            )
            return {"ok": True, "mode": "clip", "text": clipped}
        await self._announce_vc_reply(context, clipped)
        return {"ok": True, "mode": "text", "text": clipped}

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
                "said in a channel. Also use first when they ask about the last/"
                "latest YouTube video posted in a channel — then call "
                "youtube_transcript on the newest YouTube URL in those messages. "
                "Summarize results for speech; never invent video titles."
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
