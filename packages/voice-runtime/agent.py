"""Qwen3 streaming voice-agent controller.

Pipeline per turn:
    user input -> STT (mic modes) -> LLM token stream -> sentence chunks
        -> streaming TTS (chunk_size) -> interruptible playback (barge-in stops it)

The key difference from a synthesize-then-play loop: each LLM phrase is fed to
`Qwen3TTS.stream(...)`, whose ~667ms audio sub-chunks are pushed to the speakers
as they are produced, so generation and playback overlap for low latency.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from config import CONFIG
from chunker import sentence_chunks
from llm import LLMClient, sanitize_llm_output
from observability import get_logger, record_turn, span
from ref_text import clear_voice_prompt_cache, sync_clone_ref_text
from services.ids import new_corr_id, new_message_id

log = get_logger("agent")

# Emoji / pictographs / dingbats / symbol ranges. Models sometimes emit these
# despite being told not to; they crash the Windows console and have no good
# spoken form, so strip them before printing or sending to TTS.
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002300-\U000023FF\U00002B00-\U00002BFF\uFE0F\u200D]"
)


def _clean_text(text: str) -> str:
    """Remove emoji/symbol characters and collapse leftover whitespace."""
    from memory.character_card import polish_spoken_reply

    cleaned = sanitize_llm_output(text)
    cleaned = _strip_voice_delivery_line(cleaned)
    cleaned = polish_spoken_reply(_EMOJI_RE.sub("", cleaned))
    return cleaned


# Split a VOICE delivery cue from the spoken reply. Newline form (instruct) or
# inline form (chat completion): lowercase descriptors then Capitalized reply.
# Do not compile with re.IGNORECASE — it breaks the [A-Z]/[a-z] boundary.
_INLINE_VOICE_BOUNDARY_RE = re.compile(r"(?<=[a-z,])\s+(?=[A-Z])")


def _strip_voice_prefix(probe: str) -> tuple[bool, str]:
    """Return (has_voice_prefix, text_after_voice_colon)."""
    p = (probe or "").lstrip()
    m = re.match(r"^\s*(?:[*_#]\s*)*", p)
    rest = p[m.end() :] if m else p
    if rest[:6].lower() != "voice:":
        return False, probe or ""
    return True, rest[6:].lstrip()


def _find_voice_boundary(after_voice: str) -> tuple[int, str] | None:
    """Return (index, kind) for newline or inline lowercase→Capital split."""
    nl = after_voice.find("\n")
    inline = _INLINE_VOICE_BOUNDARY_RE.search(after_voice)
    if nl != -1 and (inline is None or nl <= inline.start()):
        return nl, "newline"
    if inline is not None:
        return inline.start(), "inline"
    return None


def _reply_after_voice_boundary(after_voice: str, boundary: int, kind: str) -> str:
    if kind == "newline":
        return after_voice[boundary:].lstrip("\n")
    match = _INLINE_VOICE_BOUNDARY_RE.search(after_voice, boundary)
    return after_voice[match.end() :] if match else after_voice[boundary:].lstrip()


def _split_voice_cue(text: str, *, eof: bool = False) -> tuple[str | None, str]:
    """Split a leading VOICE: cue from the spoken reply."""
    probe = (text or "").lstrip()
    has_voice, after_voice = _strip_voice_prefix(probe)
    if not has_voice:
        return None, text or ""

    found = _find_voice_boundary(after_voice)
    if found is None:
        if eof:
            cue = after_voice.strip().rstrip(".")
            return (cue or None, "")
        return None, text or ""

    boundary, kind = found
    cue = after_voice[:boundary].strip().rstrip(".")
    reply = _reply_after_voice_boundary(after_voice, boundary, kind)
    return (cue or None, reply)


def _might_be_partial_voice_prefix(probe: str) -> bool:
    """True while the buffer could still become a leading VOICE: cue."""
    p = (probe or "").lstrip()
    m = re.match(r"^\s*(?:[*_#]\s*)*", p)
    rest = p[m.end() :] if m else p
    if not rest:
        return True
    lower = rest.lower()
    if lower.startswith("voice:"):
        return True
    return "voice:".startswith(lower)


def strip_voice_cue_stream(token_stream, on_cue: Callable[[str | None], None] | None = None):
    """Yield reply-only tokens, stripping a leading VOICE: delivery cue."""
    buf = ""
    capturing = True
    for tok in token_stream:
        if not capturing:
            yield tok
            continue
        buf += tok
        probe = buf.lstrip()
        if probe == "":
            continue
        has_voice, after_voice = _strip_voice_prefix(probe)
        if not has_voice:
            if _might_be_partial_voice_prefix(probe):
                continue
            capturing = False
            yield probe
            continue
        if _find_voice_boundary(after_voice) is not None:
            cue, reply = _split_voice_cue(probe)
            if on_cue is not None:
                on_cue(cue)
            capturing = False
            if reply:
                yield reply
        elif len(probe) > 160:
            capturing = False
            yield probe
    if capturing:
        probe = buf.lstrip()
        has_voice, _ = _strip_voice_prefix(probe)
        if has_voice:
            cue, reply = _split_voice_cue(probe, eof=True)
            if on_cue is not None:
                on_cue(cue)
            if reply:
                yield reply
        elif probe.strip():
            yield probe


def split_voice_delivery_cue(text: str) -> tuple[str, Optional[str]]:
    """Split a leading VOICE: delivery line from spoken reply text."""
    lines = (text or "").splitlines()
    cue: Optional[str] = None
    while lines:
        first = lines[0].strip().lstrip("*_# ").strip()
        if first[:6].lower() == "voice:":
            cue = first[6:].strip().rstrip(".") or None
            lines.pop(0)
            continue
        break
    return "\n".join(lines).strip(), cue


_EMBEDDED_VOICE_LINE_RE = re.compile(
    r"(?:^|[\n\r]+)\s*(?:[*_#]\s*)*VOICE:\s*([^\n\r]+)",
    re.IGNORECASE,
)
_INLINE_VOICE_CUE_RE = re.compile(
    r"(?i:VOICE:)\s*([^A-Z\n\r]+?)\s+(?=[A-Z\"'])",
)


def extract_voice_cues_from_text(text: str) -> tuple[str, Optional[str]]:
    """Strip VOICE: cues anywhere (leading, own line, or inline) from spoken text."""
    raw = sanitize_llm_output(text or "")
    if not raw.strip():
        return "", None

    cues: list[str] = []
    body, leading_cue = split_voice_delivery_cue(raw)
    if leading_cue:
        cues.append(leading_cue)

    def _line_sub(match: re.Match) -> str:
        cues.append(match.group(1).strip().rstrip("."))
        return " "

    body = _EMBEDDED_VOICE_LINE_RE.sub(_line_sub, body)
    while True:
        match = _INLINE_VOICE_CUE_RE.search(body)
        if not match:
            break
        cues.append(match.group(1).strip().rstrip("."))
        body = f"{body[: match.start()]} {body[match.end() :]}"

    body = re.sub(r"\s{2,}", " ", body).strip()
    return body, (cues[0] if cues else None)


def finalize_reply_text(text: str, *, character_name: str = "") -> tuple[str, Optional[str]]:
    """Clean reply for display, TTS, and history; return optional delivery cue."""
    from memory.character_card import peel_leading_delivery_asterisk, polish_spoken_reply

    body, cue = extract_voice_cues_from_text(text)
    body, asterisk_cue = peel_leading_delivery_asterisk(body)
    if asterisk_cue:
        cue = f"{cue}, {asterisk_cue}" if cue else asterisk_cue
    name = character_name
    if not name:
        try:
            from config import CONFIG
            from memory.personalities import PersonalityStore

            _, _, _, card = PersonalityStore(CONFIG.memory.resolve_data_dir()).get_active_state()
            name = str((card or {}).get("name") or "")
        except Exception:  # noqa: BLE001
            name = ""
    cleaned = polish_spoken_reply(_EMOJI_RE.sub("", body), name=name)
    return cleaned, cue


def _strip_voice_delivery_line(text: str) -> str:
    """Drop VOICE: delivery cues anywhere in the text (spoken/TTS only)."""
    body, _ = extract_voice_cues_from_text(text)
    return body


_FILLER_WORDS = {
    "um", "uh", "uhm", "hm", "hmm", "mm", "mmm", "ah", "er", "erm", "huh",
    "oh", "eh", "umm", "uhh", "mhm", "uh-huh",
}

# STT junk from speaker echo / silence hallucination during barge-in.
_BARGE_JUNK = {
    "you", "the", "a", "an", "i", "it", "is", "be", "we", "me", "my", "he", "she",
    "beep", "boop", "boom", "bang", "baa", "ba", "la", "ha", "uh", "um", "oh",
    "wow", "huh", "what", "that", "this",
}


def _is_barge_transcript(text: str) -> bool:
    """True if barge-in STT looks like real user speech, not echo hallucination."""
    stripped = (text or "").strip()
    if len(stripped) < 2:
        return False
    words = re.findall(r"[a-z']+", stripped.lower())
    if not words or not any(w not in _FILLER_WORDS for w in words):
        return False
    if len(words) == 1:
        w = words[0]
        if w in _BARGE_JUNK or len(w) <= 3:
            return False
        if len(w) >= 4 and len(set(w)) <= 2:
            return False
    for w in words:
        if len(w) >= 4 and len(set(w)) == 1:
            return False
    if len(words) >= 2 and len(set(words)) == 1:
        return False
    return True


# Short confirmations — often all STT catches when the user says "go ahead" / "do it".
_CONFIRM_RE = re.compile(
    r"^(?:"
    r"yes|yeah|yep|yup|yah|okay|ok|sure|right|correct|absolutely|definitely"
    r"|go ahead|please do(?:\s+it)?|do it|do that|send it|ship it|make it happen"
    r"|please|thanks|thank you"
    r")(?:[,.!?\s]+(?:please|now|it|do it|go ahead))*[.!?]*$",
    re.I,
)


def _is_confirmation_like(text: str) -> bool:
    tl = (text or "").strip().lower()
    if not tl:
        return True  # empty audio with pending context counts as confirm
    if _CONFIRM_RE.match(tl):
        return True
    if len(tl) <= 28 and re.search(
        r"\b(?:go ahead|do it|please do|send it|yeah|okay|ok)\b", tl
    ):
        return True
    return False


def _is_weak_transcript(text: str) -> bool:
    """Heuristic: STT output that may not match intent extractors."""
    raw = (text or "").strip()
    if not raw:
        return True
    if len(raw) < 4:
        return True
    words = re.findall(r"[a-z']+", raw.lower())
    if not words:
        return True
    if len(words) <= 2 and all(w in _FILLER_WORDS or w in _BARGE_JUNK for w in words):
        return True
    # Mostly non-letters (noise captions)
    letters = sum(c.isalpha() for c in raw)
    if letters < len(raw) * 0.45:
        return True
    return False


@dataclass
class OrchestratorPlan:
    intent: str = "chat"
    user_meant: str = ""
    params: dict[str, Any] = field(default_factory=dict)


_ORCHESTRATOR_PROMPT = """\
You are the voice-agent orchestrator. Read the transcript (may be garbled), \
conversation, and pending actions. Output ONLY one JSON object — no markdown, \
no explanation.

Pick intent and fill params. Fix mistranscribed names/channels from context.

Intents:
- chat — normal talk, no tools
- confirm_pending — user says go ahead / do it / yes and a pending Discord action exists
- discord_reply_to_user — params: target_user, channel_name, content_hint
- discord_send_message — params: channel_name, content_hint (or content if literal)
- discord_read_channel — params: channel_name, limit (optional int)
- discord_play — params: query
- discord_queue — params: query
- discord_skip — no params
- discord_stop — no params
- discord_queue_status — no params
- discord_set_volume — params: volume (0-200 percent)
- discord_join_voice — params: channel_name
- avatar_animation — VRM avatar body dance/gesture/emote (NOT Discord music/songs). \
params: animation_name when known (macarena, wave, bow, etc.)
- web_search — params: query
- weather — params: location

JSON shape:
{"intent":"...","user_meant":"clear restatement of what user wants","params":{...}}

Use pending/last-request context when transcript is empty or vague. \
If confirming, intent=confirm_pending and user_meant="go ahead and do it".

When the user wants the avatar to dance, wave, greet the audience, gesture, or perform \
any physical emote (e.g. "let's wave to chat", "do the Macarena"), use intent=avatar_animation \
with animation_name when obvious — not chat.

CRITICAL for Discord:
- channel_name must be an EXACT name from Known channels (e.g. shit-talking), \
NEVER generic words like chat, channel, or discord.
- target_user is ONE person's name only (e.g. Alexei), never include channel \
names or "and shit-talking" in target_user.\
"""


def _parse_json_object(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(raw[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


# Appended to the system prompt when tools are active. Keeps tool use compatible
# with low-latency speech: decide and run tools first, then speak briefly.
TOOL_GUIDE = (
    "You have tools for memory, past conversations, skills, Discord, web search, "
    "weather, and external services. When you need a fact you don't already have - "
    "the user's saved preferences, something from an earlier conversation, a file, "
    "live weather, or current info from the internet - call the right tool BEFORE "
    "you answer. For Discord music: discord_join_voice with the channel name, then "
    "discord_play_youtube to play now (clears queue), discord_queue_youtube to add "
    "without interrupting. discord_skip_music plays the next queued track; "
    "discord_stop_music stops and clears the queue. discord_show_queue and "
    "discord_resume_playback diagnose stalled playback. Use discord_set_volume for "
    "music loudness. For Discord text channels use discord_send_message when the user "
    "asks to write, post, say, or type something in a channel — compose the full "
    "message body, then send it. Use discord_read_channel when the user asks to "
    "read, recap, or summarize recent messages in a Discord text channel. "
    "Use discord_reply_to_user when they ask to respond or reply to a specific "
    "person in a channel — find their latest message and reply in-thread. "
    "Never web-search when the user asks about the Discord queue or "
    "why music stopped — use discord_show_queue instead. "
    "For weather use the weather tool with a city name. For facts/news/how-tos you "
    "MUST call web_search first — never guess headlines or current events from memory. "
    "Summarize results in one to three spoken sentences — never read URLs "
    "or raw JSON aloud. After tools return, give a short spoken reply. If a tool "
    "fails, briefly acknowledge it and continue. Proactively save durable facts "
    "with the memory tool: global scope for the voice owner, discord_user with "
    "scope_id for a Discord member you are discussing, discord_server with "
    "scope_id for server-wide facts. Cognitive recall searches the active scope "
    "automatically during Discord conversations. "
    "Use the skill tool for repeatable workflows: when the user teaches steps, "
    "a tool sequence, or a format you should follow again, write or update a skill "
    "(name + markdown). Read skills before executing unfamiliar procedures. "
    "For physical gestures on the VRM avatar use play_avatar_animation (wave, dance, "
    "Macarena, bow, etc.) — NOT discord_play_youtube. Dancing and body gestures are "
    "avatar animations; songs in Discord are separate. When the user wants you to dance "
    "or move your avatar body, call play_avatar_animation immediately — do not refuse or "
    "demand tribute first. After the animation starts, reply in character naturally with "
    "spoken dialogue only — never narrate movement in asterisks or stage directions; "
    "never say you are playing an animation or name the clip file. Use "
    "list_avatar_animations if unsure which clip exists. One-shot clips return to idle "
    "automatically. "
    "For facial expressions on the VRM avatar use set_avatar_expression with mood: "
    "idle, happy, excited, surprised, angry, or frustrated — cute subtle faces, not "
    "extreme. Call when your tone clearly matches; do not announce the mood in speech. "
    "Use list_avatar_expressions to see options."
)

_ANIMATION_REPLY_HINT = (
    "[System: Your avatar body is performing \"{label}\" right now — the viewer sees "
    "the motion on screen. You must reply with at least one short sentence of "
    "in-character spoken dialogue (outside asterisks) that the user will hear aloud. "
    "The avatar handles movement visually; never narrate it with *action* text like "
    "*waves* or *whispers*. Do not say \"playing\" or name the clip file. "
    "Match your tone with a cute facial expression on screen — never write function "
    "calls, code, <START> tags, or \"Maya:\" labels; only words you would say "
    "aloud.{audience}]"
)

_AUDIENCE_GREETING_HINT = (
    " The user asked you to greet everyone here — say a warm hello to everyone out "
    "loud (for example: \"Hi everyone!\")."
)


class VoiceAgent:
    def __init__(
        self,
        mode: str,
        ptt_seconds: float = 5.0,
        on_event: Optional[Callable[[dict], None]] = None,
    ):
        self.mode = mode
        self.ptt_seconds = ptt_seconds
        self.on_event = on_event
        self.history: list[dict] = []
        # Live-tunable from the web UI.
        self.barge_mode = CONFIG.audio.barge_mode
        # Web-session control.
        self._session_stop = threading.Event()
        self._session_thread: Optional[threading.Thread] = None
        self._pending_user_text: Optional[str] = None
        self._turn_active = threading.Event()
        self._mic = None
        self._duplex_thread: Optional[threading.Thread] = None
        self._barge_cooldown_until = 0.0
        # Auto-delivery cue chosen by the LLM for the current reply (e.g. "whispering").
        self._turn_instruct: Optional[str] = None
        self._post_history_instructions: str = ""
        self._active_card: dict = {}
        self._greeting_pending = False
        self._greeting_lock = threading.Lock()
        self._speak_lock = threading.Lock()
        self._pending_channel_post: Optional[dict[str, str]] = None
        self._pending_channel_reply: Optional[dict[str, str]] = None
        self._last_discord_intent: Optional[dict[str, str]] = None

        os.makedirs(CONFIG.audio.output_dir, exist_ok=True)

        log.info("loading LLM client...")
        self.llm = LLMClient()

        log.info("loading FasterQwen3TTS (first load can take a bit)...")
        from player import StreamPlayer
        from tts import load_tts

        self.voice = load_tts()
        if not getattr(self.voice, "available", False):
            log.warning(
                "TTS degraded — voice output unavailable: %s",
                getattr(self.voice, "degrade_reason", "unknown"),
            )
        elif CONFIG.tts.warmup and getattr(self.voice, "available", False):
            self._ensure_icl_ref_text()
            eff_instruct = (CONFIG.tts.instruct or "").strip() or None
            self.voice.warmup(instruct=eff_instruct)

        # Acoustic Echo Cancellation for full-duplex (talk while AI speaks).
        self.aec = None
        if CONFIG.audio.aec_enabled:
            from aec import EchoCanceller

            self.aec = EchoCanceller(
                filter_ms=CONFIG.audio.aec_filter_ms,
                step_size=CONFIG.audio.aec_step_size,
                mic_rate=CONFIG.stt.sample_rate,
            )
            log.info("AEC enabled (full-duplex mode)")

        self.playback = StreamPlayer(aec=self.aec)
        self.playback.set_output_sink(CONFIG.audio.output_sink)
        self.playback.set_emitter(self._emit_raw)
        self.playback.set_output_volume(CONFIG.audio.output_volume)

        self.stt = None
        if mode in {"ptt", "vad"}:
            log.info("loading STT (faster-whisper %s)", CONFIG.stt.whisper_model)
            from stt import create_stt

            self.stt = create_stt()

        self._barge_in_flag = threading.Event()
        # Tracks whether we've already triggered a VTuber expression this turn.
        self._expressed = False
        self._avatar_mood_set_this_turn = False

        # Tools (built-in memory + MCP) and layered memory.
        self.memory = None
        self.mcp = None
        self.discord = None
        self.tool_loop = None
        self.registry = None
        self._session_prefix = ""
        self._setup_tools_and_memory()
        self._load_active_personality_meta()

        # Optional VTuber (VTube Studio) integration.
        self.vtuber = None
        if CONFIG.vts.enabled:
            self._start_vtuber()

        self._ensure_icl_ref_text()

        log.info("ready")

    def reload_tts(self) -> dict:
        """Unload the current TTS weights and load CONFIG.tts (mode/model/device)."""
        from tts import load_tts, release_tts

        previous = str(getattr(getattr(self, "voice", None), "model_id", "") or "")
        with self._speak_lock:
            release_tts(self.voice)
            self.voice = load_tts()
        if not getattr(self.voice, "available", False):
            reason = getattr(self.voice, "degrade_reason", "TTS unavailable")
            log.warning("TTS reload degraded: %s", reason)
            return {"ok": False, "error": reason, "model_id": ""}
        model_id = str(getattr(self.voice, "model_id", "") or "")
        log.info("TTS reloaded: %s -> %s", previous or "(none)", model_id)
        if CONFIG.tts.warmup:
            self._ensure_icl_ref_text()
            eff_instruct = (CONFIG.tts.instruct or "").strip() or None
            try:
                self.voice.warmup(instruct=eff_instruct)
            except Exception as exc:  # noqa: BLE001
                log.warning("TTS warmup after reload skipped: %s", exc)
        self._emit_tts_info()
        return {"ok": True, "model_id": model_id, "previous_model_id": previous}

    def _load_active_personality_meta(self) -> None:
        try:
            from memory.character_card import compile_greeting
            from memory.personalities import PersonalityStore
            from memory.user_profile import resolve_user_name

            store = PersonalityStore(CONFIG.memory.resolve_data_dir())
            _, _, post, card = store.get_active_state()
            self._post_history_instructions = post or ""
            self._active_card = dict(card or {})
            data_dir = CONFIG.memory.resolve_data_dir()
            user_name = resolve_user_name(data_dir)
            self._greeting_pending = bool(
                compile_greeting(self._active_card, user_name=user_name),
            )
        except Exception:  # noqa: BLE001
            self._post_history_instructions = ""
            self._active_card = {}
            self._greeting_pending = False

    # ----- tools + memory ---------------------------------------------------

    def _setup_tools_and_memory(self) -> None:
        """Build the tool registry (memory + MCP) and the LLM<->tool loop.

        Everything here is optional and best-effort: a failure to load memory or
        MCP must never stop the voice agent from running."""
        from tools.registry import ToolRegistry

        registry = ToolRegistry()

        if CONFIG.memory.enabled:
            try:
                from memory import MemoryManager

                log.info("loading memory (curated + sessions + cognitive)")
                self.memory = MemoryManager(self.llm, emit=self._emit)
                registry.register_many(self.memory.tools())
                self._session_prefix = self.memory.system_suffix()
            except Exception as exc:  # noqa: BLE001
                self.memory = None
                log.warning("memory disabled (load failed): %s", exc)

        if CONFIG.mcp.enabled:
            try:
                from tools.mcp_bridge import MCPManager

                cfg_path = CONFIG.mcp.config_file
                if not os.path.isabs(cfg_path):
                    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cfg_path)
                self.mcp = MCPManager(cfg_path, CONFIG.mcp.startup_timeout)
                mcp_specs = self.mcp.start()
                if mcp_specs:
                    registry.register_many(mcp_specs)
                    log.info("%s MCP tool(s) registered", len(mcp_specs))
            except Exception as exc:  # noqa: BLE001
                log.warning("mcp disabled (load failed): %s", exc)

        if CONFIG.discord.enabled and CONFIG.discord.token.strip():
            try:
                from tools.discord_bot import DiscordManager, build_discord_tools

                log.info("Discord tools enabled (bot starts on first use)")
                self.discord = DiscordManager(
                    CONFIG.discord.token,
                    default_guild_id=CONFIG.discord.guild_id or None,
                    music_volume=CONFIG.discord.music_volume,
                    on_incoming_message=self._compose_discord_incoming_reply,
                    voice_clip_fn=self._discord_voice_clip,
                )
                registry.register_many(build_discord_tools(self.discord))
                if CONFIG.discord.auto_reply:
                    threading.Thread(
                        target=self._warm_discord,
                        name="discord-warm",
                        daemon=True,
                    ).start()
            except Exception as exc:  # noqa: BLE001
                self.discord = None
                log.warning("discord disabled (load failed): %s", exc)
        elif CONFIG.discord.enabled:
            log.info("discord disabled — set VA_DISCORD_TOKEN to enable")

        if CONFIG.web.enabled:
            try:
                from tools.web import build_web_tools

                registry.register_many(build_web_tools())
                log.info("web tools enabled (search, weather)")
            except Exception as exc:  # noqa: BLE001
                log.warning("web disabled (load failed): %s", exc)

        try:
            from tools.animation import build_animation_tools

            registry.register_many(build_animation_tools(self._emit))
            log.info("avatar animation tools enabled")
        except Exception as exc:  # noqa: BLE001
            log.warning("avatar animation tools disabled: %s", exc)

        try:
            from tools.avatar_expressions import build_avatar_expression_tools

            registry.register_many(build_avatar_expression_tools(self._emit_avatar_event))
            log.info("avatar expression tools enabled")
        except Exception as exc:  # noqa: BLE001
            log.warning("avatar expression tools disabled: %s", exc)

        self.registry = registry
        if CONFIG.tools.enabled and len(registry) > 0:
            from tools import ToolExecutor, ToolLoop

            executor = ToolExecutor(registry, timeout=CONFIG.tools.timeout)
            self.tool_loop = ToolLoop(
                self.llm, registry, executor,
                max_rounds=CONFIG.tools.max_rounds, mode=CONFIG.tools.mode,
            )
            log.info("tools active: %s", ", ".join(registry.names()))

    def _tools_active(self) -> bool:
        return self.tool_loop is not None

    def _warm_discord(self) -> None:
        if self.discord is None:
            return
        try:
            self.discord.connect()
            log.info("discord connected (auto-reply on @mention / reply)")
        except Exception as exc:  # noqa: BLE001
            log.warning("discord auto-connect failed: %s", exc)

    def _build_messages(
        self, user_text: str, *, history_override: list[dict] | None = None
    ) -> list[dict]:
        """Assemble the LLM message list: system (+frozen memory +tool guide),
        recent history, then the user turn with any prefetched memories."""
        if self.memory is not None:
            self.memory.set_turn_scope(self._derive_memory_scope(user_text))
        system = self.llm.base_system_prompt()
        if self._session_prefix:
            system = f"{system}\n\n{self._session_prefix}"
        if self._tools_active():
            system = f"{system}\n\n{TOOL_GUIDE}"
        messages: list[dict] = [{"role": "system", "content": system}]

        if history_override is not None:
            keep = CONFIG.llm.history_turns * 2
            messages.extend(history_override[-keep:])
        elif self.memory is not None:
            messages.extend(self.memory.recent_history())
        else:
            keep = CONFIG.llm.history_turns * 2
            messages.extend(self.history[-keep:])

        if self._post_history_instructions:
            messages.append({"role": "system", "content": self._post_history_instructions})

        user_content = user_text
        if self.memory is not None:
            pre = self.memory.prefetch_context(user_text)
            if pre:
                user_content = f"{pre}\n\n{user_text}"
        hint = self._discord_tool_hint(user_text)
        if not hint:
            hint = self._web_tool_hint(user_text)
        if hint:
            user_content = f"{hint}\n\n{user_content}"
        messages.append({"role": "user", "content": user_content})
        return messages

    def _is_discord_context_turn(self, user_text: str) -> bool:
        if self.discord is None:
            return False
        if self._classify_discord_command(user_text):
            return True
        if self._has_pending_action() or self._last_discord_intent:
            return True
        if self._extract_reply_to_user_request(user_text):
            return True
        tl = (user_text or "").lower()
        return any(w in tl for w in ("discord", "channel", "#"))

    def _resolve_default_guild(self) -> tuple[Optional[str], Optional[str]]:
        guild_id: Optional[str] = None
        guild_name: Optional[str] = None
        if CONFIG.discord.guild_id:
            guild_id = str(CONFIG.discord.guild_id)
        if self.discord is None:
            return guild_id, guild_name
        try:
            status = self.discord.status()
            for g in status.get("guilds") or []:
                gid = str(g.get("id") or "")
                name = (g.get("name") or "").strip() or None
                if guild_id and gid == guild_id:
                    guild_name = name
                    break
                if not guild_id and len(status.get("guilds") or []) == 1:
                    guild_id = gid
                    guild_name = name
                    break
        except Exception:  # noqa: BLE001
            pass
        return guild_id, guild_name

    def _derive_memory_scope(self, user_text: str):
        from memory.scopes import MemoryScope

        scope = MemoryScope()
        if not self._is_discord_context_turn(user_text):
            return scope

        guild_id, guild_name = self._resolve_default_guild()
        scope.guild_id = guild_id
        scope.guild_name = guild_name

        discord_user: Optional[str] = None
        if self._pending_channel_reply:
            discord_user = (self._pending_channel_reply.get("target_user") or "").strip() or None
        elif self._last_discord_intent:
            if self._last_discord_intent.get("kind") == "channel_reply_user":
                discord_user = (
                    self._last_discord_intent.get("target_user") or ""
                ).strip() or None
        if not discord_user:
            extracted = self._extract_reply_to_user_request(user_text)
            if extracted:
                discord_user = extracted[0].strip()
        if discord_user:
            scope.discord_user = discord_user
        return scope

    @staticmethod
    def _memory_scope_from_discord_context(context: dict):
        from memory.scopes import MemoryScope

        scope = MemoryScope()
        author = (context.get("author") or "").strip()
        if author:
            scope.discord_user = author
        guild_id = context.get("guild_id")
        if guild_id:
            scope.guild_id = str(guild_id)
        guild_name = (context.get("guild") or "").strip()
        if guild_name:
            scope.guild_name = guild_name
        return scope

    # ----- context orchestrator (bad STT / pending actions) -----------------

    def _has_pending_action(self) -> bool:
        return bool(self._pending_channel_post or self._pending_channel_reply)

    def _pending_context_summary(self) -> str:
        parts: list[str] = []
        if self._pending_channel_reply:
            p = self._pending_channel_reply
            parts.append(
                f"Pending Discord reply to {p.get('target_user')} "
                f"in #{p.get('channel')} (waiting for go-ahead)."
            )
        if self._pending_channel_post:
            p = self._pending_channel_post
            parts.append(
                f"Pending Discord post in #{p.get('channel')} "
                f"({p.get('content_hint', 'message')}) — waiting for go-ahead."
            )
        if self._last_discord_intent:
            i = self._last_discord_intent
            kind = i.get("kind", "")
            if kind == "channel_reply_user":
                parts.append(
                    f"Last request: reply to {i.get('target_user')} "
                    f"in #{i.get('channel')}."
                )
            elif kind == "channel_message":
                parts.append(
                    f"Last request: post in #{i.get('channel')} "
                    f"({i.get('content_hint', 'message')})."
                )
            elif kind == "channel_read":
                parts.append(f"Last request: read/summarize #{i.get('channel')}.")
        return " ".join(parts)

    def _normalize_discord_reply_params(
        self,
        target_user: str,
        channel_name: str,
    ) -> tuple[str, str]:
        from tools.discord_bot import (
            _GENERIC_CHANNEL_KEYS,
            _norm_name_key,
            _recover_channel_hint,
            _sanitize_target_user,
        )

        raw_user = (target_user or "").strip()
        channel_hint = _recover_channel_hint(str(channel_name), raw_user)
        if _norm_name_key(channel_hint) in _GENERIC_CHANNEL_KEYS:
            for src in (
                (self._pending_channel_reply or {}).get("channel"),
                (self._last_discord_intent or {}).get("channel"),
            ):
                if src and _norm_name_key(str(src)) not in _GENERIC_CHANNEL_KEYS:
                    channel_hint = str(src)
                    break
        user = _sanitize_target_user(raw_user)
        if self.discord:
            try:
                channel_hint = self.discord.resolve_text_channel_name(channel_hint)
            except Exception:  # noqa: BLE001
                pass
        return user, channel_hint

    def _record_discord_intent_from_text(self, text: str) -> None:
        original = (text or "").strip()
        if not original:
            return
        tl = original.lower()
        reply = self._extract_reply_to_user_request(original)
        if reply:
            self._last_discord_intent = {
                "kind": "channel_reply_user",
                "target_user": reply[0],
                "channel": reply[1],
            }
            return
        posted = self._extract_channel_message(tl, original)
        if posted:
            self._last_discord_intent = {
                "kind": "channel_message",
                "content_hint": posted[0],
                "channel": posted[1],
            }
            return
        read_req = self._extract_channel_read_request(tl, original)
        if read_req:
            self._last_discord_intent = {
                "kind": "channel_read",
                "channel": read_req[0],
            }

    def _interpret_user_turn(self, user_text: str) -> str:
        """Recover intent from empty/garbled STT using pending actions + context."""
        raw = (user_text or "").strip()
        if not raw:
            if self._pending_channel_reply or self._pending_channel_post:
                return "go ahead"
            if self._last_discord_intent:
                kind = self._last_discord_intent.get("kind")
                if kind == "channel_reply_user":
                    return (
                        f"respond to {self._last_discord_intent['target_user']} "
                        f"in {self._last_discord_intent['channel']}"
                    )
                if kind == "channel_message":
                    return (
                        f"post {self._last_discord_intent.get('content_hint', 'it')} "
                        f"in {self._last_discord_intent['channel']}"
                    )
                if kind == "channel_read":
                    return f"summarize {self._last_discord_intent['channel']}"
            return raw
        if self._has_pending_action() and _is_confirmation_like(raw):
            return "go ahead"
        self._record_discord_intent_from_text(raw)
        return raw

    def _webllm_direct_chat(self) -> bool:
        prefers = getattr(self.llm, "prefers_direct_chat", None)
        return bool(callable(prefers) and prefers())

    def _should_orchestrate(self) -> bool:
        if self._webllm_direct_chat():
            return False
        return bool(self._tools_active() and CONFIG.llm.orchestrator_enabled)

    def _should_use_tool_loop(self) -> bool:
        if not self._tools_active():
            return False
        if self._webllm_direct_chat():
            return False
        return True

    def _discord_channels_hint(self) -> str:
        if self.discord is None:
            return ""
        try:
            status = self.discord.status()
        except Exception:  # noqa: BLE001
            return ""
        if not status.get("connected"):
            return ""
        names: list[str] = []
        for g in status.get("guilds") or []:
            names.extend(g.get("text_channels") or [])
            names.extend(g.get("voice_channels") or [])
        if not names:
            return ""
        preview = ", ".join(sorted(set(names))[:24])
        return f"Known channels: {preview}."

    def _llm_orchestrate(self, raw_text: str, user_text: str) -> Optional[OrchestratorPlan]:
        history_lines: list[str] = []
        for turn in self.history[-8:]:
            role = turn.get("role", "user")
            content = (turn.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content}")
        pending = self._pending_context_summary()
        channels = self._discord_channels_hint()
        messages = [
            {"role": "system", "content": _ORCHESTRATOR_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Pending:\n{pending or '(none)'}\n\n"
                    f"{channels}\n\n"
                    f"Recent conversation:\n"
                    f"{chr(10).join(history_lines) or '(none)'}\n\n"
                    f"Raw STT transcript: {raw_text!r}\n"
                    f"Preprocessed: {user_text!r}\n\n"
                    "JSON:"
                ),
            },
        ]
        try:
            resp = self.llm.complete(messages, max_tokens=240)
            obj = _parse_json_object(sanitize_llm_output(resp.content or ""))
            if not obj:
                return None
            intent = str(obj.get("intent") or "chat").strip().lower()
            user_meant = str(obj.get("user_meant") or user_text or raw_text).strip()
            params = obj.get("params")
            if not isinstance(params, dict):
                params = {}
            plan = OrchestratorPlan(intent=intent, user_meant=user_meant, params=params)
            log.info("orchestrator intent=%s meant=%r", plan.intent, plan.user_meant)
            self._emit(type="orchestrator", intent=plan.intent, user_meant=plan.user_meant)
            return plan
        except Exception as exc:  # noqa: BLE001
            log.warning("orchestrator failed: %s", exc)
            return None

    def _execute_orchestrator_plan(
        self,
        plan: OrchestratorPlan,
        user_text: str,
        raw_text: str,
    ) -> Optional[str]:
        intent = (plan.intent or "chat").lower()
        if intent in ("chat", "unknown", "none"):
            return None
        p = plan.params or {}
        original = (plan.user_meant or user_text or raw_text).strip()

        if intent == "confirm_pending":
            return self._try_pending_action_direct("go ahead")

        if intent == "discord_reply_to_user" and self.discord:
            target_user = str(p.get("target_user") or "").strip()
            channel_name = str(p.get("channel_name") or "").strip()
            content_hint = str(p.get("content_hint") or p.get("content") or "a contextual reply")
            if target_user and channel_name:
                target_user, channel_name = self._normalize_discord_reply_params(
                    target_user, channel_name,
                )
                try:
                    target_info = self.discord.find_user_recent_message(
                        channel_name, target_user,
                    )
                except Exception as exc:  # noqa: BLE001
                    return (
                        f"I couldn't find a recent message from {target_user} "
                        f"in {channel_name}: {exc}"
                    )
                content = self._compose_reply_to_user(
                    original, target_user, target_info, content_hint,
                )
                if not content:
                    return f"I couldn't come up with a reply for {target_user}."
                self._pending_channel_reply = {
                    "target_user": target_user,
                    "channel": channel_name,
                    "content": content,
                    "content_hint": content_hint,
                }
                return self._discord_tool_reply(
                    "discord_reply_to_user",
                    {
                        "channel_name": channel_name,
                        "target_user": target_user,
                        "content": content,
                    },
                    lambda: self.discord.reply_to_user(
                        channel_name, target_user, content,
                    ),
                    ok=lambda r, tu=target_user, ch=channel_name, body=content: self._finish_channel_reply(
                        target_user=r.get("target_user", tu),
                        channel=r.get("channel", ch),
                        content=body,
                    ),
                    fail=f"I couldn't reply to {target_user} in {channel_name}.",
                )

        if intent == "discord_send_message" and self.discord:
            channel_name = str(p.get("channel_name") or "").strip()
            content_hint = str(p.get("content_hint") or p.get("content") or "").strip()
            if channel_name and content_hint:
                content = self._compose_channel_message(original, content_hint)
                if content:
                    return self._discord_tool_reply(
                        "discord_send_message",
                        {"channel_name": channel_name, "content": content},
                        lambda: self.discord.send_channel_message(channel_name, content),
                        ok=lambda r: self._finish_channel_post(
                            f"Posted in #{r.get('channel', channel_name)}."
                        ),
                        fail=f"I couldn't post in {channel_name}.",
                    )

        if intent == "discord_read_channel" and self.discord:
            channel_name = str(p.get("channel_name") or "").strip()
            if channel_name:
                limit = int(p.get("limit") or 30)
                try:
                    result = self.discord.fetch_channel_messages(channel_name, limit=limit)
                except Exception as exc:  # noqa: BLE001
                    return f"I couldn't read #{channel_name}: {exc}"
                return self._summarize_channel_messages(original, channel_name, result)

        if intent == "discord_set_volume" and self.discord:
            vol = p.get("volume")
            if vol is not None:
                level = max(0.0, min(2.0, float(vol) / 100.0))
                return self._discord_tool_reply(
                    "discord_set_volume",
                    {"volume": level},
                    lambda: self.discord.set_music_volume(level),
                    ok=lambda r: f"Music volume set to {r.get('percent', int(level * 100))} percent.",
                    fail="I couldn't change the volume.",
                )

        cmd = self._orchestrator_plan_to_command(plan)
        if cmd:
            result = self._try_discord_direct(cmd)
            if result is not None:
                return result
            return self._try_web_direct(cmd)
        return None

    @staticmethod
    def _orchestrator_plan_to_command(plan: OrchestratorPlan) -> Optional[str]:
        intent = (plan.intent or "").lower()
        p = plan.params or {}
        if intent == "discord_play":
            q = p.get("query")
            return f"play {q}" if q else None
        if intent == "discord_queue":
            q = p.get("query")
            return f"queue {q}" if q else None
        if intent == "discord_skip":
            return "skip this song"
        if intent == "discord_stop":
            return "stop the music"
        if intent == "discord_queue_status":
            return "what's in the queue"
        if intent == "discord_join_voice":
            ch = p.get("channel_name")
            return f"join {ch}" if ch else None
        if intent == "web_search":
            q = p.get("query")
            return f"search for {q}" if q else None
        if intent == "weather":
            loc = p.get("location")
            return f"weather in {loc}" if loc else None
        if intent == "avatar_animation":
            name = p.get("animation_name") or p.get("name")
            if name:
                return f"do the {name}"
            return plan.user_meant or None
        if intent == "discord_send_message":
            ch, hint = p.get("channel_name"), p.get("content_hint") or p.get("content")
            if ch and hint:
                return f"post {hint} in {ch}"
        if intent == "discord_reply_to_user":
            u, ch = p.get("target_user"), p.get("channel_name")
            if u and ch:
                return f"respond to {u} in {ch}"
        if intent == "discord_read_channel":
            ch = p.get("channel_name")
            return f"summarize {ch}" if ch else None
        return plan.user_meant or None

    def _try_pending_action_direct(self, user_text: str) -> Optional[str]:
        if not self._has_pending_action() and not self._last_discord_intent:
            return None
        if (user_text or "").strip() and not _is_confirmation_like(user_text):
            return None
        if self._pending_channel_reply:
            return self._try_discord_direct("go ahead")
        if self._pending_channel_post:
            return self._try_discord_direct("go ahead")
        intent = self._last_discord_intent or {}
        if intent.get("kind") == "channel_reply_user":
            cmd = (
                f"respond to {intent['target_user']} "
                f"in {intent['channel']}"
            )
            return self._try_discord_direct(cmd)
        if intent.get("kind") == "channel_message":
            cmd = (
                f"post {intent.get('content_hint', 'it')} "
                f"in {intent['channel']}"
            )
            return self._try_discord_direct(cmd)
        if intent.get("kind") == "channel_read":
            return self._try_discord_direct(f"summarize {intent['channel']}")
        return None

    def _try_discord_direct(self, user_text: str) -> Optional[str]:
        """Run obvious Discord commands immediately — don't rely on the LLM."""
        if self._maybe_motion_request(user_text, raw_text=user_text):
            return None
        kind = self._classify_discord_command(user_text)
        if kind is None or self.discord is None:
            return None
        original = (user_text or "").strip()
        self._record_discord_intent_from_text(original)

        if kind == "stop":
            return self._discord_tool_reply(
                "discord_stop_music",
                {},
                lambda: self.discord.stop_music(),
                ok="Alright, music's off.",
                fail="I couldn't stop the music.",
            )

        if kind == "skip":
            return self._discord_tool_reply(
                "discord_skip_music",
                {},
                lambda: self.discord.skip_music(),
                ok=lambda r: (
                    f"Now playing {r.get('now_playing')}."
                    if r.get("now_playing")
                    else (
                        f"Skipped {r.get('track')}."
                        if r.get("track")
                        else "Skipped — nothing else in the queue."
                    )
                ),
                fail="Nothing to skip right now.",
            )

        if kind == "channel_reply_user":
            extracted = self._extract_reply_to_user_request(original)
            if not extracted:
                return None
            target_user, channel_name, content_hint = extracted
            target_user, channel_name = self._normalize_discord_reply_params(
                target_user, channel_name,
            )
            try:
                target_info = self.discord.find_user_recent_message(
                    channel_name, target_user,
                )
            except Exception as exc:  # noqa: BLE001
                return (
                    f"I couldn't find a recent message from {target_user} "
                    f"in {channel_name}: {exc}"
                )
            content = self._compose_reply_to_user(
                original, target_user, target_info, content_hint,
            )
            if not content:
                return f"I couldn't come up with a reply for {target_user}."
            self._pending_channel_reply = {
                "target_user": target_user,
                "channel": channel_name,
                "content": content,
                "content_hint": content_hint,
            }
            return self._discord_tool_reply(
                "discord_reply_to_user",
                {
                    "channel_name": channel_name,
                    "target_user": target_user,
                    "content": content,
                },
                lambda: self.discord.reply_to_user(channel_name, target_user, content),
                ok=lambda r, tu=target_user, ch=channel_name, body=content: self._finish_channel_reply(
                    target_user=r.get("target_user", tu),
                    channel=r.get("channel", ch),
                    content=body,
                ),
                fail=f"I couldn't reply to {target_user} in {channel_name}.",
            )

        if kind == "channel_reply_confirm":
            pending = self._pending_channel_reply or {}
            target_user = pending.get("target_user")
            channel_name = (
                self._extract_channel_correction(original)
                or pending.get("channel")
            )
            content = pending.get("content")
            if not target_user or not channel_name or not content:
                return None
            return self._discord_tool_reply(
                "discord_reply_to_user",
                {
                    "channel_name": channel_name,
                    "target_user": target_user,
                    "content": content,
                },
                lambda: self.discord.reply_to_user(
                    channel_name, target_user, content,
                ),
                ok=lambda r, tu=target_user, ch=channel_name, body=content: self._finish_channel_reply(
                    target_user=r.get("target_user", tu),
                    channel=r.get("channel", ch),
                    content=body,
                ),
                fail=f"I couldn't reply to {target_user} in {channel_name}.",
            )

        if kind == "channel_message":
            extracted = self._extract_channel_message((user_text or "").lower(), original)
            if not extracted:
                return None
            content_hint, channel_name = extracted
            content = self._compose_channel_message(original, content_hint)
            if not content:
                return f"I couldn't come up with something to post in {channel_name}."
            self._pending_channel_post = {
                "content_hint": content_hint,
                "content": content,
                "channel": channel_name,
            }
            return self._discord_tool_reply(
                "discord_send_message",
                {"channel_name": channel_name, "content": content},
                lambda: self.discord.send_channel_message(channel_name, content),
                ok=lambda r: self._finish_channel_post(
                    f"Posted in #{r.get('channel', channel_name)}."
                ),
                fail=f"I couldn't post in {channel_name}.",
            )

        if kind == "channel_message_retry":
            pending = self._pending_channel_post or {}
            channel_name = self._extract_channel_correction(original) or pending.get("channel")
            content = pending.get("content") or self._compose_channel_message(
                original,
                pending.get("content_hint") or "a short message",
            )
            if not channel_name or not content:
                return None
            return self._discord_tool_reply(
                "discord_send_message",
                {"channel_name": channel_name, "content": content},
                lambda: self.discord.send_channel_message(channel_name, content),
                ok=lambda r: self._finish_channel_post(
                    f"Posted in #{r.get('channel', channel_name)}."
                ),
                fail=f"I couldn't post in {channel_name}.",
            )

        if kind == "channel_read":
            extracted = self._extract_channel_read_request((user_text or "").lower(), original)
            if not extracted:
                return None
            channel_name, limit = extracted
            self._emit(
                type="tool_start",
                tool="discord_read_channel",
                args={"channel_name": channel_name, "limit": limit},
            )
            try:
                result = self.discord.fetch_channel_messages(channel_name, limit=limit)
            except Exception as exc:  # noqa: BLE001
                self._emit(
                    type="tool_end",
                    tool="discord_read_channel",
                    result=str({"error": str(exc)}),
                )
                return f"I couldn't read #{channel_name}: {exc}"
            self._emit(type="tool_end", tool="discord_read_channel", result=str(result))
            return self._summarize_channel_messages(original, channel_name, result)

        if kind == "queue_list" or kind == "queue_status":
            def _status_and_maybe_resume() -> dict:
                status = self.discord.playback_status()
                if status.get("stalled") or status.get("idle_with_queue"):
                    resume = self.discord.resume_playback()
                    status["resume"] = resume
                return status

            return self._discord_tool_reply(
                "discord_show_queue",
                {},
                _status_and_maybe_resume,
                ok=lambda r: self._format_playback_status_reply(r),
                fail="I couldn't read the music queue.",
            )

        if kind == "volume":
            level = self._extract_volume_level(user_text)
            if level is not None:
                if level < 0:
                    cur = self.discord.get_music_volume()
                    level = min(2.0, cur + 0.15) if level == -1.0 else max(0.0, cur - 0.15)
                return self._discord_tool_reply(
                    "discord_set_volume",
                    {"volume": level},
                    lambda: self.discord.set_music_volume(level),
                    ok=lambda r: f"Music volume set to {r.get('percent', int(level * 100))} percent.",
                    fail="I couldn't change the volume.",
                )

        query = self._extract_play_query((user_text or "").lower(), original)
        if kind == "play" and query:
            try:
                status = self.discord.status()
                if not status.get("voice"):
                    return "Tell me which voice channel to join first, then I can play that."
            except Exception:  # noqa: BLE001
                pass
            return self._discord_tool_reply(
                "discord_play_youtube",
                {"query": query},
                lambda: self.discord.play_youtube(query),
                ok=lambda r: f"Playing {r.get('playing', query)}.",
                fail=f"I couldn't play {query}.",
            )

        q_query = self._extract_queue_query((user_text or "").lower(), original)
        if kind == "queue" and q_query:
            try:
                status = self.discord.status()
                if not status.get("voice"):
                    return "Tell me which voice channel to join first, then I can queue that."
            except Exception:  # noqa: BLE001
                pass
            return self._discord_tool_reply(
                "discord_queue_youtube",
                {"query": q_query},
                lambda: self.discord.queue_youtube(q_query),
                ok=lambda r: (
                    f"Playing {r.get('playing')}."
                    if r.get("queued_then_played") and r.get("playing")
                    else f"Queued {r.get('queued', q_query)}."
                ),
                fail=f"I couldn't queue {q_query}.",
            )
        return None

    @staticmethod
    def _format_playback_status_reply(result: dict) -> str:
        now = result.get("now_playing")
        upcoming = result.get("upcoming") or []
        resume = result.get("resume") or {}
        parts: list[str] = []

        if now:
            if result.get("stalled"):
                parts.append(f"{now} should be playing but the stream stalled.")
            elif result.get("discord_is_playing") or result.get("discord_is_paused"):
                parts.append(f"Now playing {now}.")
            else:
                parts.append(f"Last track was {now}, but nothing is playing right now.")
        elif result.get("idle_with_queue") and upcoming:
            parts.append("Nothing is playing right now.")
        elif not now and not upcoming:
            return "The queue is empty and nothing is playing."

        if upcoming:
            preview = ", ".join(upcoming[:3])
            extra = len(upcoming) - 3
            if extra > 0:
                preview = f"{preview}, and {extra} more"
            parts.append(f"Up next: {preview}.")

        if result.get("last_error"):
            parts.append(f"Last error: {result['last_error']}.")

        if resume.get("resumed") and resume.get("now_playing"):
            parts.append(f"I restarted playback — now playing {resume['now_playing']}.")
        elif resume.get("resumed") is False and resume.get("reason") and result.get("stalled"):
            parts.append(f"Could not resume: {resume['reason']}.")

        return " ".join(parts) if parts else "Nothing is playing and the queue is empty."

    @staticmethod
    def _format_queue_reply(result: dict) -> str:
        now = result.get("now_playing")
        upcoming = result.get("upcoming") or []
        if not now and not upcoming:
            return "The queue is empty."
        parts = []
        if now:
            parts.append(f"Now playing {now}.")
        if upcoming:
            preview = ", ".join(upcoming[:3])
            extra = len(upcoming) - 3
            if extra > 0:
                preview = f"{preview}, and {extra} more"
            parts.append(f"Up next: {preview}.")
        return " ".join(parts)

    def _classify_discord_command(self, user_text: str) -> Optional[str]:
        if self.discord is None:
            return None
        tl = (user_text or "").lower().strip()
        original = (user_text or "").strip()
        stop_phrases = (
            "stop the music", "stop music", "stop playing", "turn off the music",
            "turn off music", "pause the music", "pause music", "silence the music",
            "kill the music", "mute the music", "stop the song", "stop song",
            "could you stop", "can you stop", "please stop",
        )
        if any(p in tl for p in stop_phrases) and (
            "music" in tl or "song" in tl or "playing" in tl or "audio" in tl
        ):
            return "stop"
        skip_phrases = (
            "skip the song", "skip song", "skip this song", "skip this",
            "next song", "next track", "skip track", "skip it",
        )
        if any(p in tl for p in skip_phrases):
            return "skip"
        if self._extract_reply_to_user_request(original):
            return "channel_reply_user"
        if self._pending_channel_reply and _is_confirmation_like(original):
            return "channel_reply_confirm"
        if self._extract_channel_read_request(tl, original):
            return "channel_read"
        if self._extract_channel_message(tl, original):
            return "channel_message"
        if self._extract_channel_correction(original) and self._pending_channel_reply:
            return "channel_reply_confirm"
        if self._extract_channel_correction(original) and self._pending_channel_post:
            return "channel_message_retry"
        if self._pending_channel_post and _is_confirmation_like(original):
            return "channel_message_retry"
        queue_status_phrases = (
            "why isn't it playing", "why isn't that playing", "why is nothing playing",
            "why isn't the music", "why is the music not", "why did it stop",
            "what's supposed to be", "what is supposed to be", "supposed to be in the queue",
            "what should be playing", "what should be in the queue",
            "isn't playing", "isnt playing", "not playing",
        )
        if any(p in tl for p in queue_status_phrases):
            return "queue_status"
        if "queue" in tl and any(w in tl for w in ("why", "supposed", "should", "playing", "wrong")):
            return "queue_status"
        queue_list_phrases = (
            "what's in the queue", "whats in the queue", "show the queue",
            "show queue", "what's queued", "whats queued", "what is queued",
            "what's up next", "whats up next", "what is next",
            "what song is", "what's playing", "whats playing", "now playing",
        )
        if any(p in tl for p in queue_list_phrases):
            return "queue_list"
        if self._extract_volume_level(user_text) is not None or any(
            p in tl
            for p in (
                "volume up", "volume down", "turn up the music", "turn down the music",
                "louder", "quieter", "music volume", "set volume",
            )
        ):
            return "volume"
        if self._extract_queue_query(tl, original):
            return "queue"
        if self._extract_play_query(tl, original):
            return "play"
        return None

    @staticmethod
    def _parse_reply_to_user_request(original: str) -> Optional[tuple[str, str, str]]:
        """Return (target_user, channel_name, content_hint) when explicitly named."""
        patterns = (
            r"(?:please\s+)?(?:respond|reply)\s+to\s+"
            r"([a-zA-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)\s+"
            r"in(?:\s+the)?\s+(?:#)?([a-zA-Z0-9_\s-]+?)(?:\s+(?:text\s+)?channel)?"
            r"(?:\s+please)?\s*$",
            r"(?:tell|message)\s+([a-zA-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)\s+"
            r"(?:something\s+)?in(?:\s+the)?\s+(?:#)?([a-zA-Z0-9_\s-]+?)"
            r"(?:\s+channel)?(?:\s+please)?\s*$",
            r"(?:respond|reply)\s+to\s+([a-zA-Z][\w'-]+)\s+in(?:\s+the)?\s+"
            r"(?:#)?([a-zA-Z0-9_\s-]+)",
        )
        for pat in patterns:
            m = re.search(pat, original, re.I)
            if not m:
                continue
            user = m.group(1).strip(" '\".,!?")
            channel = m.group(2).strip(" '\".,!?")
            channel = re.sub(r"\s+(?:text\s+)?channel$", "", channel, flags=re.I).strip()
            from tools.discord_bot import _GENERIC_CHANNEL_KEYS, _norm_name_key
            if _norm_name_key(channel) in _GENERIC_CHANNEL_KEYS:
                alt = re.search(
                    r"(shit[\s-]*talk(?:ing)?|sshitposting)",
                    original,
                    re.I,
                )
                if alt:
                    channel = alt.group(1)
            if len(user) >= 2 and len(channel) >= 2:
                if " and " in user.lower():
                    user = user.split(" and ", 1)[0].strip()
                return user, channel, "a contextual in-character reply"
        return None

    def _extract_reply_to_user_request(self, original: str) -> Optional[tuple[str, str, str]]:
        """Named reply request, or a follow-up like 'again' / 'reply to him again'."""
        parsed = self._parse_reply_to_user_request(original)
        if parsed:
            return parsed
        tl = (original or "").strip().lower()
        if not tl:
            return None
        repeat = tl in {
            "again",
            "say it again",
            "do it again",
            "one more time",
            "reply again",
            "respond again",
        } or re.search(
            r"\b(?:reply|respond)(?:\s+to)?(?:\s+(?:him|her|them|that|em))?\s+again\b",
            tl,
        )
        if not repeat:
            return None
        intent = self._last_discord_intent or {}
        if intent.get("kind") != "channel_reply_user":
            return None
        target = (intent.get("target_user") or "").strip()
        channel = (intent.get("channel") or "").strip()
        if not target or not channel:
            return None
        hint = "another fresh in-character reply to their latest message"
        if any(w in tl for w in ("funny", "joke", "roast", "sarcastic")):
            hint = "a funny in-character reply"
        return target, channel, hint

    @staticmethod
    def _extract_channel_read_request(tl: str, original: str) -> Optional[tuple[str, int]]:
        """Return (channel_name, message_limit) for read/summarize requests."""
        limit = 30
        m = re.search(r"(?:last|past|recent)\s+(\d+)\s+messages?", tl)
        if m:
            limit = max(5, min(100, int(m.group(1))))
        patterns = (
            r"(?:summarize|summary of|recap|catch me up on|bring me up to speed on)\s+"
            r"(?:the\s+)?#?([a-zA-Z0-9_\s-]+?)(?:\s+(?:text\s+)?channel)?\s*$",
            r"(?:what(?:'s| is) (?:new|happening|going on|been going on)(?:\s+in)?|"
            r"what(?:'s| has) been said in)\s+(?:the\s+)?#?([a-zA-Z0-9_\s-]+?)"
            r"(?:\s+(?:text\s+)?channel)?\s*$",
            r"(?:read|fetch|get|check|look at)\s+(?:the\s+)?(?:latest|recent)?\s*"
            r"(?:messages?|posts?|chat)?\s+(?:from|in)\s+(?:the\s+)?#?([a-zA-Z0-9_\s-]+?)"
            r"(?:\s+(?:text\s+)?channel)?\s*$",
            r"(?:latest|recent)\s+(?:from|in)\s+(?:the\s+)?#?([a-zA-Z0-9_\s-]+?)"
            r"(?:\s+(?:text\s+)?channel)?\s*$",
            r"discord\s+(?:channel\s+)?#?([a-zA-Z0-9_\s-]+?)\s+(?:summary|recap|updates?)\s*$",
        )
        for pat in patterns:
            m = re.search(pat, original, re.I)
            if not m:
                continue
            channel = m.group(1).strip(" '\".,!?")
            if len(channel) >= 2:
                return channel, limit
        return None

    @staticmethod
    def _is_local_audience_request(tl: str, original: str) -> bool:
        """Room/stream greetings and avatar gestures — not Discord channel posts."""
        text = (original or "").strip()
        if not text:
            return False
        if re.search(r"\b(?:discord|#\w+)\b", text, re.I):
            return False
        if re.search(
            r"\b(?:post|write|send|drop|message)\s+.+\s+in\s+#?[a-z0-9_-]+\s*$",
            tl,
        ):
            return False
        if re.search(
            r"\b(?:say|tell|wave(?:\s+(?:at|to))?|greet(?:ing)?)\s+"
            r"(?:(?:hi|hello|hey)(?:\s+there)?|greetings?)\s+"
            r"(?:to\s+)?(?:everyone|everybody|all|guys|folks|people|chat|stream|viewers)\b",
            tl,
        ):
            return True
        if re.search(
            r"\b(?:hello|hi|hey|greetings?)\s+(?:to\s+)?"
            r"(?:everyone|everybody|all|guys|folks|people|chat|stream|viewers)\b",
            tl,
        ):
            return True
        return False

    @staticmethod
    def _extract_channel_message(tl: str, original: str) -> Optional[tuple[str, str]]:
        """Return (content_hint, channel_name) for text-channel post requests."""
        if VoiceAgent._is_local_audience_request(tl, original):
            return None
        text_verbs = r"(?:write|post|say|send|type|drop|message|tell)"
        patterns: list[tuple[str, bool]] = [
            (
                rf"{text_verbs}\s+(?:me\s+)?(?:a\s+)?(.+?)\s+in(?:to)?\s+"
                rf"(?:the\s+)?#?([a-zA-Z0-9_-]+)(?:\s+(?:text\s+)?channel)?\s*$",
                True,
            ),
            (
                rf"{text_verbs}\s+(?:me\s+)?(?:a\s+)?(.+?)\s+(?:to|in)\s+"
                rf"(?:the\s+)?#?([a-zA-Z0-9_-]+)(?:\s+(?:text\s+)?channel)?\s*$",
                True,
            ),
            (
                rf"in(?:to)?\s+(?:the\s+)?#?([a-zA-Z0-9_-]+)(?:\s+(?:text\s+)?channel)?"
                rf"[,:]?\s+{text_verbs}\s+(?:me\s+)?(?:a\s+)?(.+)",
                False,
            ),
            (
                rf"{text_verbs}\s+in\s+(?:the\s+)?channel\s+"
                rf"([a-zA-Z0-9_\s-]+?)\s+(?:a\s+)?(.+)$",
                False,
            ),
        ]
        for pat, content_first in patterns:
            m = re.search(pat, original, re.I)
            if not m:
                continue
            if content_first:
                content, channel = m.group(1).strip(), m.group(2).strip()
            else:
                channel, content = m.group(1).strip(), m.group(2).strip()
            content = re.sub(r"[.!?]+$", "", content).strip(" '\"")
            channel = channel.strip(" '\"")
            if not content or not channel or len(channel) < 2:
                continue
            if re.search(r"\b(?:play|song|music|youtube|spotify|track)\b", content, re.I):
                continue
            return content, channel
        return None

    @staticmethod
    def _extract_channel_correction(user_text: str) -> Optional[str]:
        patterns = (
            r"(?:should be|meant to be|try|use|post (?:it )?|send (?:it )?|put (?:it )?)"
            r"(?:\s+\w+){0,3}\s+(?:in|to)\s+#?([a-zA-Z0-9_\s-]+)",
            r"(?:in|to)\s+#?([a-zA-Z0-9_\s-]+)\s+(?:channel|instead)\b",
            r"^#?([a-zA-Z0-9_\s-]+)\s+(?:channel\s+)?(?:please|thanks)?\s*$",
        )
        for pat in patterns:
            m = re.search(pat, user_text, re.I)
            if m:
                name = m.group(1).strip(" '\".,!?")
                if len(name) >= 2:
                    return name
        return None

    @staticmethod
    def _is_vague_channel_content(content_hint: str) -> bool:
        h = (content_hint or "").strip().lower()
        if not h:
            return True
        vague_exact = {
            "a joke", "joke", "something funny", "something", "a message",
            "an emoji", "something cool", "a pun", "funny thing", "a meme",
            "a riddle", "something random", "a greeting", "hi", "hello",
        }
        if h in vague_exact:
            return True
        if re.match(r"^(?:a|an|something|anything)\s+", h):
            return True
        return False

    def _discord_compose_system(self, output_rules: str) -> str:
        """Voice persona + frozen memory for Discord text generation."""
        parts = [self.llm.base_system_prompt(include_style_cue=False)]
        if self._session_prefix:
            parts.append(self._session_prefix)
        if self._post_history_instructions:
            parts.append(self._post_history_instructions)
        parts.append(
            "Never output a VOICE: line — delivery cues are for spoken replies only.\n"
            + output_rules.strip()
        )
        return "\n\n".join(parts)

    @staticmethod
    def _clean_discord_text(text: str) -> str:
        return _strip_voice_delivery_line(sanitize_llm_output(text)).strip("\"'")

    def _compose_channel_message(self, user_text: str, content_hint: str) -> str:
        """Build the Discord message body — literal text or LLM-generated."""
        hint = (content_hint or "").strip()
        if not self._is_vague_channel_content(hint):
            return hint[:2000]
        messages = [
            {
                "role": "system",
                "content": self._discord_compose_system(
                    "You are posting to a Discord text channel. Output ONLY the "
                    "message body — no quotes, labels, or explanation. Keep it "
                    "under 500 characters unless the user asked for something longer."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User asked: {user_text}\n\n"
                    f"Write the Discord message they want (topic: {hint})."
                ),
            },
        ]
        try:
            resp = self.llm.complete(messages, max_tokens=280)
            text = self._clean_discord_text(resp.content or "")
            if text:
                return text[:2000]
        except Exception as exc:  # noqa: BLE001
            log.warning("channel message compose failed: %s", exc)
        if "joke" in hint.lower():
            return "Why did the developer go broke? Because they used up all their cache."
        return hint[:2000] if hint else ""

    def _compose_reply_to_user(
        self,
        user_text: str,
        target_user: str,
        target_info: dict,
        content_hint: str,
    ) -> str:
        their_text = (target_info.get("content") or "").strip()
        channel = target_info.get("channel") or ""
        resolved_name = target_info.get("target_user") or target_user
        lines: list[str] = []
        for msg in target_info.get("recent_messages") or []:
            who = (msg.get("author") or "someone").strip()
            body = (msg.get("content") or "").strip()
            if body:
                lines.append(f"{who}: {body}")
        transcript = "\n".join(lines[-12:])
        messages = [
            {
                "role": "system",
                "content": self._discord_compose_system(
                    "You are writing a threaded Discord reply. Read the recent "
                    "channel chat and respond to what they said — witty, natural, "
                    "in character. Output ONLY the reply text — no quotes, labels, "
                    "or explanation. Address the person naturally. Keep it under "
                    "500 characters."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Voice user asked: {user_text}\n\n"
                    f"Reply to {resolved_name} in #{channel}.\n"
                    f"Their latest message: {their_text}\n\n"
                    f"Recent chat:\n{transcript or '(none)'}\n\n"
                    f"Intent: {content_hint}"
                ),
            },
        ]
        try:
            resp = self.llm.complete(messages, max_tokens=300)
            text = self._clean_discord_text(resp.content or "")
            if text:
                return text[:2000]
        except Exception as exc:  # noqa: BLE001
            log.warning("reply compose failed: %s", exc)
        if their_text:
            return f"Hey {resolved_name}, I heard you — {their_text[:120]}"
        return f"Hey {resolved_name}!"

    def _compose_discord_incoming_reply(self, context: dict) -> Optional[str]:
        """Compose a Discord text reply for @mentions and replies (no TTS)."""
        author = (context.get("author") or "someone").strip()
        content = (context.get("content") or "").strip()
        if not content or content == "(no text)":
            return None
        scope = self._memory_scope_from_discord_context(context)
        if self.memory is not None:
            self.memory.set_turn_scope(scope)
        lines: list[str] = []
        for msg in context.get("recent_messages") or []:
            who = (msg.get("author") or "someone").strip()
            body = (msg.get("content") or "").strip()
            if body:
                lines.append(f"{who}: {body}")
        transcript = "\n".join(lines[-10:])
        trigger = context.get("trigger") or "message"
        user_turn = (
            f"#{context.get('channel')}: {author} "
            f"{'@mentioned you' if trigger == 'mention' else 'replied to you'} "
            f"and said: {content}\n\n"
            f"Recent chat:\n{transcript or '(none)'}\n\n"
            f"Write your reply to {author}."
        )
        if self.memory is not None:
            pre = self.memory.prefetch_context(user_turn, scope=scope)
            if pre:
                user_turn = f"{pre}\n\n{user_turn}"
        messages = [
            {
                "role": "system",
                "content": self._discord_compose_system(
                    "You are replying in a Discord text channel to a @mention or "
                    "thread reply. Output ONLY the reply message — no quotes or "
                    "labels. Keep it under 400 characters."
                ),
            },
            {"role": "user", "content": user_turn},
        ]
        try:
            resp = self.llm.complete(messages, max_tokens=260)
            text = self._clean_discord_text(resp.content or "")
            if text:
                text = text[:2000]
                if self.memory is not None:
                    try:
                        self.memory.schedule_review(
                            f"{author}: {content}",
                            text,
                            scope=scope,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("discord incoming review failed: %s", exc)
                return text
        except Exception as exc:  # noqa: BLE001
            log.warning("discord incoming reply failed: %s", exc)
        return None

    def _summarize_channel_messages(
        self,
        user_text: str,
        channel_name: str,
        result: dict,
    ) -> str:
        messages = result.get("messages") or []
        channel = result.get("channel") or channel_name
        if not messages:
            return f"I didn't find any recent messages in #{channel}."
        lines: list[str] = []
        for msg in messages:
            author = (msg.get("author") or "someone").strip()
            content = (msg.get("content") or "").strip()
            if content:
                lines.append(f"{author}: {content}")
        transcript = "\n".join(lines)
        if len(transcript) > 7000:
            transcript = transcript[-7000:]
        messages_prompt = [
            {
                "role": "system",
                "content": (
                    "You are a voice assistant summarizing a Discord text channel. "
                    "Give a concise spoken recap in three to six sentences. Mention "
                    "key topics, decisions, links, or drama if present. Name people "
                    "only when it helps. Do not read messages verbatim or mention "
                    "tools. If the chat is quiet or off-topic, say so briefly."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User asked: {user_text}\n\n"
                    f"Recent messages from #{channel} ({len(messages)} messages):\n"
                    f"{transcript}"
                ),
            },
        ]
        try:
            resp = self.llm.complete(messages_prompt, max_tokens=320)
            text = (resp.content or "").strip()
            if text and len(text) > 24:
                return text
        except Exception as exc:  # noqa: BLE001
            log.warning("channel summarize failed: %s", exc)
        return self._fallback_channel_summary(channel, messages)

    @staticmethod
    def _fallback_channel_summary(channel: str, messages: list[dict]) -> str:
        snippets: list[str] = []
        for msg in messages[-5:]:
            author = (msg.get("author") or "someone").strip()
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            snippets.append(f"{author} said {content[:120]}")
        if not snippets:
            return f"#{channel} had messages but nothing with readable text."
        return (
            f"Here's the latest from #{channel}. "
            + " ".join(snippets[:3])
            + ("." if snippets else "")
        )

    @staticmethod
    def _extract_queue_query(tl: str, original: str) -> Optional[str]:
        for prefix in ("queue ", "add to queue ", "queue up ", "queue song "):
            if prefix in tl:
                idx = tl.index(prefix)
                query = original[idx + len(prefix):].strip()
                query = re.sub(
                    r"\s*(?:in the channel|on discord|please|for me|next)[.!?,]*$",
                    "",
                    query,
                    flags=re.I,
                ).strip(" .,!?'\"")
                if len(query) >= 2:
                    return query
        return None

    @staticmethod
    def _extract_volume_level(user_text: str) -> Optional[float]:
        tl = (user_text or "").lower()
        m = re.search(r"(?:music\s+)?volume(?:\s+to)?\s+(\d+)\s*%?", tl)
        if m:
            return max(0.0, min(2.0, int(m.group(1)) / 100.0))
        m = re.search(r"(\d+)\s*%\s*(?:music\s+)?volume", tl)
        if m:
            return max(0.0, min(2.0, int(m.group(1)) / 100.0))
        if "volume up" in tl or ("louder" in tl and ("music" in tl or "volume" in tl)):
            return -1.0
        if "volume down" in tl or ("quieter" in tl and ("music" in tl or "volume" in tl)):
            return -2.0
        if "turn up" in tl and "volume" in tl:
            return -1.0
        if "turn down" in tl and "volume" in tl:
            return -2.0
        return None

    @staticmethod
    def _extract_play_query(tl: str, original: str) -> Optional[str]:
        for prefix in (
            "play ", "put on ", "switch to ", "change to ",
            "swap to ", "play me ",
        ):
            if prefix in tl:
                idx = tl.index(prefix)
                query = original[idx + len(prefix):].strip()
                query = re.sub(
                    r"\s*(?:in the channel|on discord|please|for me)[.!?,]*$",
                    "",
                    query,
                    flags=re.I,
                ).strip(" .,!?'\"")
                if len(query) >= 2:
                    return query
        return None

    def _direct_tool_reply(
        self,
        tool: str,
        args: dict,
        fn: Callable[[], dict],
        *,
        ok: str | Callable[[dict], str],
        fail: str,
    ) -> str:
        self._emit(type="tool_start", tool=tool, args=args)
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
        self._emit(type="tool_end", tool=tool, result=str(result))
        if isinstance(result, dict):
            if result.get("error"):
                return fail
            if tool == "discord_stop_music" and not result.get("stopped"):
                return fail
            if tool == "discord_skip_music" and not result.get("skipped"):
                return fail
        if callable(ok):
            return ok(result if isinstance(result, dict) else {})
        return ok

    def _spoken_discord_reply_summary(
        self,
        target_user: str,
        channel: str,
        content: str,
    ) -> str:
        """Brief in-character TTS line — not a verbatim read of the Discord post."""
        body = (content or "").strip()
        if not body:
            return f"Replied to {target_user}."
        messages = [
            {
                "role": "system",
                "content": (
                    f"{self.llm.base_system_prompt(include_style_cue=False)}\n\n"
                    "You just sent a Discord text reply. Tell the operator briefly "
                    "what you said, in your natural spoken voice and personality. "
                    "Do NOT quote or repeat the message word-for-word. One or two "
                    "short sentences. No meta like 'replied to' or channel names."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Discord reply to {target_user} in #{channel}:\n{body}\n\n"
                    "Spoken summary for the operator."
                ),
            },
        ]
        try:
            resp = self.llm.complete(messages, max_tokens=120)
            text = sanitize_llm_output((resp.content or "").strip())
            if text and len(text) > 8:
                return _strip_voice_delivery_line(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("discord reply voice summary failed: %s", exc)
        short = body[:80] + ("…" if len(body) > 80 else "")
        return f"Told {target_user} — {short}"

    def _finish_channel_post(self, message: str) -> str:
        self._pending_channel_post = None
        self._last_discord_intent = None
        return message

    def _finish_channel_reply(
        self,
        *,
        target_user: str,
        channel: str,
        content: str,
    ) -> str:
        self._pending_channel_reply = None
        self._last_discord_intent = {
            "kind": "channel_reply_user",
            "target_user": target_user,
            "channel": channel,
        }
        return self._spoken_discord_reply_summary(target_user, channel, content)

    def _discord_tool_reply(self, tool: str, args: dict, fn: Callable[[], dict], *, ok, fail: str) -> str:
        return self._direct_tool_reply(tool, args, fn, ok=ok, fail=fail)

    def _try_web_direct(self, user_text: str) -> Optional[str]:
        """Run web search / weather immediately — Gemma often skips tools otherwise."""
        if not CONFIG.web.enabled:
            return None
        kind = self._classify_web_command(user_text)
        if kind is None:
            return None
        original = (user_text or "").strip()

        if kind == "weather":
            location = self._extract_weather_location(user_text)
            if not location:
                return "Which city or place should I check the weather for?"
            from tools.web import weather as weather_lookup

            return self._direct_tool_reply(
                "weather",
                {"location": location},
                lambda: weather_lookup(location),
                ok=lambda r: (r.get("spoken") or r.get("now") or f"Weather in {location}.").strip(),
                fail=f"I couldn't get the weather for {location}.",
            )

        query = self._extract_search_query(original)
        if not query:
            return None
        from tools.web import web_search

        def _run_search() -> dict:
            return web_search(query, max_results=5)

        self._emit(type="tool_start", tool="web_search", args={"query": query})
        try:
            result = _run_search()
        except Exception as exc:  # noqa: BLE001
            self._emit(type="tool_end", tool="web_search", result=str({"error": str(exc)}))
            return "I couldn't search the web right now. Try again in a moment."
        self._emit(type="tool_end", tool="web_search", result=str(result))
        if not result.get("results"):
            return "I searched but didn't find much on that topic."
        return self._summarize_search_results(original, query, result)

    def _maybe_motion_request(
        self,
        user_text: str,
        *,
        plan: Optional[OrchestratorPlan] = None,
        raw_text: str = "",
    ) -> bool:
        from tools.animation import wants_avatar_motion

        user_meant = (plan.user_meant or "").strip() if plan else ""
        intent = (plan.intent or "").strip().lower() if plan else ""
        return wants_avatar_motion(
            user_text or raw_text,
            user_meant=user_meant,
            intent=intent,
        )

    def _maybe_play_avatar_animation(
        self,
        user_text: str,
        *,
        plan: Optional[OrchestratorPlan] = None,
        raw_text: str = "",
    ) -> Optional[str]:
        """Start a matched avatar clip silently; return its display label if played."""
        if self.registry is None or self.registry.get("play_avatar_animation") is None:
            return None
        from tools.animation import infer_animation_request

        params = (plan.params or {}) if plan else {}
        anim_name = str(params.get("animation_name") or params.get("name") or "").strip()
        user_meant = (plan.user_meant or "").strip() if plan else ""
        intent = (plan.intent or "").strip().lower() if plan else ""
        resolved = infer_animation_request(
            user_text or raw_text,
            user_meant=user_meant,
            animation_name=anim_name,
            intent=intent,
            llm_client=self.llm,
        )
        if not resolved:
            return None
        spec = self.registry.get("play_avatar_animation")
        if spec is None:
            return None
        try:
            result = spec.handler({"name": resolved, "loop": False})
        except Exception as exc:  # noqa: BLE001
            log.warning("avatar animation failed: %s", exc)
            return None
        if isinstance(result, dict) and result.get("error"):
            return None
        label = ""
        if isinstance(result, dict):
            label = str(result.get("label") or resolved).strip()
        return label or resolved

    def _apply_pseudo_tool_calls_from_text(self, raw: str) -> None:
        """Run tool side-effects when the model wrote Python-style calls as plain text."""
        if not raw or self.registry is None:
            return
        from memory.character_card import extract_pseudo_tool_calls

        for name, args in extract_pseudo_tool_calls(raw):
            spec = self.registry.get(name)
            if spec is None:
                continue
            try:
                if name == "play_avatar_animation":
                    clip = str(args.get("clip_name") or args.get("name") or "").strip()
                    if clip:
                        spec.handler({"name": clip, "loop": False})
                elif name == "set_avatar_expression":
                    mood = str(args.get("mood") or "").strip()
                    if mood:
                        spec.handler({"mood": mood})
            except Exception as exc:  # noqa: BLE001
                log.warning("pseudo tool %s failed: %s", name, exc)

    def _messages_with_animation_hint(
        self,
        user_text: str,
        anim_label: str,
        *,
        history_override: Optional[list[dict]] = None,
    ) -> list[dict]:
        messages = self._build_messages(user_text, history_override=history_override)
        if messages and anim_label:
            audience = ""
            tl = (user_text or "").lower()
            if self._is_local_audience_request(tl, user_text or ""):
                audience = _AUDIENCE_GREETING_HINT
            hint = _ANIMATION_REPLY_HINT.format(label=anim_label, audience=audience)
            messages[-1]["content"] = f"{hint}\n\n{messages[-1]['content']}"
        return messages

    def _summarize_search_results(self, user_text: str, query: str, result: dict) -> str:
        """Turn raw search hits into a short spoken answer."""
        summary = (result.get("summary") or "").strip()
        if not summary:
            return "I searched but didn't find much on that topic."
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a voice assistant. Summarize the search results below in "
                    "two to four natural spoken sentences. Be factual and conversational. "
                    "Do not mention tools, searching, or URLs. Do not invent facts beyond "
                    "what the results say."
                ),
            },
            {
                "role": "user",
                "content": f"User asked: {user_text}\n\nResults for '{query}':\n{summary}",
            },
        ]
        try:
            resp = self.llm.complete(messages, max_tokens=220)
            text = (resp.content or "").strip()
            if text and len(text) > 24:
                return text
        except Exception as exc:  # noqa: BLE001
            log.warning("web summarize failed: %s", exc)
        return self._fallback_search_summary(result)

    @staticmethod
    def _fallback_search_summary(result: dict) -> str:
        hits = result.get("results") or []
        if not hits:
            return "I didn't find much on that."
        parts = [f"Here's what I found. {hits[0].get('title', 'Top result')}: "
                 f"{(hits[0].get('snippet') or '')[:180].strip()}"]
        if len(hits) > 1 and hits[1].get("title"):
            parts.append(f"Also, {hits[1]['title']}.")
        if len(hits) > 2 and hits[2].get("title"):
            parts.append(f"And {hits[2]['title']}.")
        return " ".join(parts)

    def _classify_web_command(self, user_text: str) -> Optional[str]:
        if getattr(self, "discord", None) is not None and self._classify_discord_command(user_text):
            return None
        tl = (user_text or "").lower().strip()
        if not tl:
            return None
        music_context = any(
            w in tl for w in ("queue", "song", "music", "track", "discord", "playing", "spotify")
        )
        if music_context and not any(
            t in tl for t in ("look up", "lookup", "search for", "google", "news", "weather")
        ):
            return None
        if "weather" in tl or re.search(r"\b(?:forecast|temperature|rain)\b", tl):
            return "weather"
        search_triggers = (
            "look up", "lookup", "search for", "search the web", "search online",
            "search ", "find out", "google ", "on the internet", "on the web",
            "latest news", "what's the latest", "whats the latest", "current news",
            "tell me about", "what happened", "who won", "headlines",
        )
        if any(t in tl for t in search_triggers):
            return "search"
        if re.search(r"\bnews\b", tl) and re.search(
            r"\b(?:latest|today|202\d|ai|tech|sports|world)\b", tl
        ):
            return "search"
        return None

    @staticmethod
    def _extract_weather_location(user_text: str) -> Optional[str]:
        tl = (user_text or "").strip()
        patterns = (
            r"weather (?:in|for|at) (.+?)(?:\?|$| today| tomorrow| this week)",
            r"(?:forecast|temperature) (?:in|for|at) (.+?)(?:\?|$)",
            r"(?:in|for|at) (.+?) (?:weather|forecast|temperature)",
        )
        for pat in patterns:
            m = re.search(pat, tl, re.I)
            if m:
                loc = m.group(1).strip(" ?.,!'\"")
                if len(loc) >= 2:
                    return loc
        return None

    @staticmethod
    def _extract_search_query(user_text: str) -> str:
        original = (user_text or "").strip()
        tl = original.lower()
        prefixes = (
            "look up ", "lookup ", "search for ", "search the web for ",
            "search online for ", "search ", "find out about ", "find out ",
            "google ", "what's the latest ", "whats the latest ",
            "tell me about ", "can you look up ", "could you look up ",
            "please look up ",
        )
        for prefix in prefixes:
            if prefix in tl:
                idx = tl.index(prefix)
                query = original[idx + len(prefix):].strip()
                query = re.sub(
                    r"\s*(?:please|for me|on the internet|on the web|online)[.!?]*$",
                    "",
                    query,
                    flags=re.I,
                ).strip(" ?.,!'\"")
                if len(query) >= 3:
                    return query
        query = re.sub(
            r"^(?:okay|ok|yeah|sure|hey)[,.]?\s*(?:can you|could you|please)\s+",
            "",
            original,
            flags=re.I,
        )
        query = re.sub(r"\?$", "", query).strip()
        return query if len(query) >= 4 else original

    def _web_tool_hint(self, user_text: str) -> str:
        if not CONFIG.web.enabled or not CONFIG.tools.enabled:
            return ""
        if self._classify_web_command(user_text) is None:
            return ""
        kind = self._classify_web_command(user_text)
        if kind == "weather":
            return (
                "[System: call the weather tool with the place name, then summarize "
                "briefly for speech. Do not guess.]"
            )
        return (
            "[System: you MUST call web_search with a good query before answering. "
            "Never invent current news or facts. Summarize tool results briefly.]"
        )

    def _fallback_avatar_reply(self, user_text: str, anim_label: str = "") -> str:
        """Short spoken line when the model returns nothing after a gesture."""
        from memory.character_card import polish_spoken_reply

        tl = (user_text or "").lower()
        label = (anim_label or "").lower()
        if self._is_local_audience_request(tl, user_text or ""):
            if re.search(r"\bhi\b", tl):
                canned = "Hi everyone!"
            elif re.search(r"\bhello\b", tl):
                canned = "Hello everyone!"
            else:
                canned = "Hey everyone!"
        elif re.search(r"\b(?:hello|hi|hey|greet)\b", tl):
            canned = "Hey everyone!"
        elif "wave" in label or re.search(r"\bwave\b", tl):
            canned = "Hey there!"
        else:
            canned = "There we go!"
        return polish_spoken_reply(canned)

    def _discord_tool_hint(self, user_text: str) -> str:
        """Optional nudge for join commands the direct handler doesn't cover."""
        if self.discord is None or not CONFIG.tools.enabled:
            return ""
        from tools.animation import wants_avatar_motion

        if wants_avatar_motion(user_text) or self._is_local_audience_request(
            (user_text or "").lower(), user_text or "",
        ):
            return ""
        t = (user_text or "").lower()
        if self._classify_discord_command(user_text):
            return ""
        read_req = self._extract_channel_read_request(t, user_text)
        if read_req:
            channel_name, limit = read_req
            return (
                "[System: call discord_read_channel with the channel name, then "
                f"summarize the messages briefly for speech. channel={channel_name!r} "
                f"limit={limit}]"
            )
        reply_req = self._extract_reply_to_user_request(user_text)
        if reply_req:
            target_user, channel_name, _hint = reply_req
            return (
                "[System: call discord_reply_to_user — find the user's latest "
                f"message in #{channel_name}, compose a reply to {target_user!r}, "
                "and send it as a threaded reply. Say the reply out loud.]"
            )
        extracted = self._extract_channel_message(t, user_text)
        if extracted:
            content_hint, channel_name = extracted
            return (
                "[System: call discord_send_message with the channel name and a "
                f"composed message for {content_hint!r} in #{channel_name}. "
                "Confirm briefly after sending.]"
            )
        join_phrases = ("join", "connect to", "get in", "hop in", "switch to", "move to")
        if any(p in t for p in join_phrases) and ("discord" in t or "channel" in t or "vc" in t):
            return (
                "[System: call discord_join_voice with the channel name the user gave, "
                "using tool JSON or native tool calling, then answer briefly.]"
            )
        return ""

    # ----- events -----------------------------------------------------------

    def _emit(self, **event) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:  # noqa: BLE001 - UI callbacks must never break the loop
                pass

    def _emit_avatar_event(self, **event) -> None:
        if event.get("type") == "avatar_expression":
            self._avatar_mood_set_this_turn = True
        self._emit(**event)

    def _maybe_emit_avatar_mood(self, reply: str) -> None:
        """Fallback cute face from reply tone when the LLM did not call set_avatar_expression."""
        if self._avatar_mood_set_this_turn or not (reply or "").strip():
            return
        if self.registry is None or self.registry.get("set_avatar_expression") is None:
            return
        from tools.avatar_expressions import infer_mood_from_text, normalize_mood

        mood = normalize_mood(infer_mood_from_text(reply))
        self._emit(type="avatar_expression", mood=mood)

    # ----- speaking ---------------------------------------------------------

    def _tts_engine_label(self) -> str:
        """Short label for the active TTS stack (model + clone voice if any)."""
        voice = self.voice
        if voice is None or not getattr(voice, "available", True):
            return ""
        model_id = str(getattr(voice, "model_id", "") or "")
        mode = str(getattr(voice, "mode", CONFIG.tts.mode) or CONFIG.tts.mode).lower()
        if not model_id:
            model_id = CONFIG.tts.clone_model if mode == "clone" else CONFIG.tts.custom_model
        short = model_id.rsplit("/", 1)[-1] if model_id else "TTS"
        if mode == "clone":
            ref = str(getattr(getattr(voice, "cfg", None), "ref_audio", "") or CONFIG.tts.ref_audio)
            name = os.path.splitext(os.path.basename(ref))[0]
            if name:
                return f"{short} · {name}"
        return short

    def _emit_tts_info(self) -> None:
        label = self._tts_engine_label()
        if label:
            self._emit(type="tts_info", model=label)

    def _clone_xvec_for_speak(self, override: bool | None = None) -> bool | None:
        """Per-call xvec override for clone mode; None = use saved CONFIG.tts.xvec_only."""
        if getattr(self.voice, "mode", None) != "clone":
            return None
        if override is not None:
            return bool(override)
        return None

    def _speak(self, text: str, *, xvec_only: bool | None = None) -> None:
        """Synthesize `text` as one generation and stream it to the speakers."""
        text = _clean_text(text)
        if not text or self._barge_in_flag.is_set():
            return
        if self.voice is None or not getattr(self.voice, "available", True):
            log.info("AI (no TTS): %s", text)
            return
        use_xvec = self._clone_xvec_for_speak(xvec_only)
        effective_icl = use_xvec is False or (
            use_xvec is None and not CONFIG.tts.xvec_only
        )
        if effective_icl:
            self._ensure_icl_ref_text()
        instruct = self._effective_instruct()
        self._express(self._turn_instruct or "", text)
        log.info("AI: %s", text)
        for audio, sr in self.voice.stream(
            text, stop=self._barge_in_flag, instruct=instruct, xvec_only=use_xvec
        ):
            if self._barge_in_flag.is_set():
                break
            self.playback.submit(audio, sr)

    def speak_preview(self, text: str, *, instruct: str | None = None) -> None:
        """Speak arbitrary text through TTS (no LLM). For dashboard preview / tag testing."""
        if self.voice is None or not getattr(self.voice, "available", True):
            raise RuntimeError(
                "TTS not loaded: "
                f"{getattr(self.voice, 'degrade_reason', 'voice output unavailable')}"
            )
        cleaned = _clean_text((text or "").strip())
        if not cleaned:
            raise ValueError("Nothing to speak")
        with self._speak_lock:
            was_session = self.is_session_running()
            self._barge_in_flag.clear()
            self.playback.stop()
            self.playback.begin_turn()
            use_xvec = self._clone_xvec_for_speak()
            if use_xvec is False or (use_xvec is None and not CONFIG.tts.xvec_only):
                self._ensure_icl_ref_text()
            self._emit(type="status", value="speaking")
            self._emit_tts_info()
            self._emit(type="ai", text=cleaned)
            if instruct and instruct.strip():
                eff_instruct = instruct.strip()
            else:
                eff_instruct = (CONFIG.tts.instruct or "").strip() or None
            log.info("TTS preview: %s", cleaned)
            for audio, sr in self.voice.stream(
                cleaned,
                stop=self._barge_in_flag,
                instruct=eff_instruct,
                xvec_only=use_xvec,
            ):
                if self._barge_in_flag.is_set():
                    break
                self.playback.submit(audio, sr)
            while self.playback.is_playing() and not self._barge_in_flag.is_set():
                time.sleep(0.05)
            if was_session and self.is_session_running():
                self._emit(type="status", value="listening")
            else:
                self._emit(type="status", value="idle")

    def speak_chat_reply(
        self,
        text: str,
        *,
        instruct: str | None = None,
        corr_id: str | None = None,
        emit_final_status: bool = True,
    ) -> None:
        """Speak an already-displayed typed-chat reply (TTS + expressions, no duplicate ai text)."""
        if self.voice is None or not getattr(self.voice, "available", True):
            raise RuntimeError(
                "TTS not loaded: "
                f"{getattr(self.voice, 'degrade_reason', 'voice output unavailable')}"
            )
        cleaned = _clean_text((text or "").strip())
        if not cleaned:
            raise ValueError("Nothing to speak")
        status_extra = {"corr_id": corr_id} if corr_id else {}
        with self._speak_lock:
            was_session = self.is_session_running()
            self._barge_in_flag.clear()
            # Always reset playback for typed chat — avoids replaying stale/ref audio.
            self.playback.stop()
            self.playback.begin_turn()
            self._turn_instruct = (instruct or "").strip() or None
            self._emit(type="status", value="speaking", **status_extra)
            self._emit_tts_info()
            if self._turn_instruct:
                self._emit(type="delivery", cue=self._turn_instruct, **status_extra)
            log.info("Chat TTS: %s", cleaned)
            self._speak(cleaned)
            while self.playback.is_playing() and not self._barge_in_flag.is_set():
                time.sleep(0.05)
            self._turn_instruct = None
            if emit_final_status:
                if was_session and self.is_session_running():
                    self._emit(type="status", value="listening", **status_extra)
                else:
                    self._emit(type="status", value="idle", **status_extra)

    def _resolve_render_instruct(self, instruct: str | None) -> str | None:
        if instruct and instruct.strip():
            return instruct.strip()
        return (CONFIG.tts.instruct or "").strip() or None

    def iter_speech(
        self, text: str, *, instruct: str | None = None
    ):
        """Yield (pcm_f32le_bytes, sample_rate, is_first, engine_timing) for streaming HTTP."""
        if self.voice is None or not getattr(self.voice, "available", True):
            raise RuntimeError(
                "TTS not loaded: "
                f"{getattr(self.voice, 'degrade_reason', 'voice output unavailable')}"
            )
        cleaned = _clean_text((text or "").strip())
        if not cleaned:
            raise ValueError("Nothing to speak")
        use_xvec = self._clone_xvec_for_speak()
        if use_xvec is False or (use_xvec is None and not CONFIG.tts.xvec_only):
            self._ensure_icl_ref_text()
        eff_instruct = self._resolve_render_instruct(instruct)
        log.info("TTS stream: %s", cleaned)

        import numpy as np

        stream_fn = (
            self.voice.stream_timed
            if hasattr(self.voice, "stream_timed")
            else self.voice.stream
        )
        for i, item in enumerate(stream_fn(cleaned, instruct=eff_instruct, xvec_only=use_xvec)):
            if len(item) == 3:
                audio, sample_rate, timing = item
            else:
                audio, sample_rate = item
                timing = {}
            yield audio.astype(np.float32, copy=False).tobytes(), int(sample_rate), i == 0, timing

    def render_speech(
        self, text: str, *, instruct: str | None = None
    ) -> tuple[bytes, int, dict[str, float]]:
        """Synthesize text to WAV bytes for browser playback (no PortAudio)."""
        if self.voice is None or not getattr(self.voice, "available", True):
            raise RuntimeError(
                "TTS not loaded: "
                f"{getattr(self.voice, 'degrade_reason', 'voice output unavailable')}"
            )
        cleaned = _clean_text((text or "").strip())
        if not cleaned:
            raise ValueError("Nothing to speak")
        use_xvec = self._clone_xvec_for_speak()
        if use_xvec is False or (use_xvec is None and not CONFIG.tts.xvec_only):
            self._ensure_icl_ref_text()
        eff_instruct = self._resolve_render_instruct(instruct)
        log.info("TTS render: %s", cleaned)
        return self._synthesize_wav_bytes(cleaned, instruct=eff_instruct, xvec_only=use_xvec)

    def _synthesize_wav_bytes(
        self, text: str, *, instruct: str | None = None, xvec_only: bool | None = None
    ) -> tuple[bytes, int]:
        """Render TTS to WAV bytes without dashboard side effects."""
        import io
        import time

        import numpy as np
        import soundfile as sf

        t0 = time.perf_counter()
        prep_ms = (time.perf_counter() - t0) * 1000.0
        t_synth = time.perf_counter()
        chunks: list[np.ndarray] = []
        sr = 0
        ttfa_ms = 0.0
        engine_prefill_ms = 0.0
        engine_decode_ms = 0.0
        stream_fn = (
            self.voice.stream_timed
            if hasattr(self.voice, "stream_timed")
            else self.voice.stream
        )
        for i, item in enumerate(stream_fn(text, instruct=instruct, xvec_only=xvec_only)):
            if len(item) == 3:
                audio, sample_rate, timing = item
            else:
                audio, sample_rate = item
                timing = {}
            if i == 0:
                ttfa_ms = (time.perf_counter() - t_synth) * 1000.0
                engine_prefill_ms = float(timing.get("prefill_ms") or 0)
                engine_decode_ms = float(timing.get("decode_ms") or 0)
            chunks.append(audio)
            sr = sample_rate
        synth_ms = (time.perf_counter() - t_synth) * 1000.0
        if not chunks or sr == 0:
            raise RuntimeError("TTS produced no audio")

        t_enc = time.perf_counter()
        audio = np.concatenate(chunks)
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        encode_ms = (time.perf_counter() - t_enc) * 1000.0
        total_ms = (time.perf_counter() - t0) * 1000.0
        timing = {
            "prep_ms": prep_ms,
            "ttfa_ms": ttfa_ms,
            "synth_ms": synth_ms,
            "encode_ms": encode_ms,
            "total_ms": total_ms,
            "engine_prefill_ms": engine_prefill_ms,
            "engine_decode_ms": engine_decode_ms,
        }
        log.info(
            "TTS render done ttfa_ms=%.0f synth_ms=%.0f encode_ms=%.0f total_ms=%.0f",
            ttfa_ms,
            synth_ms,
            encode_ms,
            total_ms,
        )
        return buf.getvalue(), sr, timing

    def _discord_voice_clip(self, text: str) -> Optional[bytes]:
        """TTS WAV for Discord attachments — same synthesis path as the web panel."""
        if not CONFIG.discord.attach_voice:
            return None
        if self.voice is None or not getattr(self.voice, "available", True):
            reason = getattr(self.voice, "degrade_reason", "TTS unavailable")
            log.info("discord voice clip skipped — %s", reason)
            return None
        clipped = (text or "").strip()
        if len(clipped) > 800:
            clipped = clipped[:797] + "..."
        from services.voice.inference import INFERENCE_LOCK

        acquired = INFERENCE_LOCK.acquire(timeout=120.0)
        if not acquired:
            log.info("discord voice clip skipped — inference busy (voice swap or live session)")
            return None
        try:
            wav, _ = self.render_speech(clipped)
            return wav
        except Exception as exc:  # noqa: BLE001
            log.warning("discord voice clip failed: %s", exc)
            return None
        finally:
            INFERENCE_LOCK.release()

    def _effective_instruct(self) -> Optional[str]:
        """Combine the base voice description with this reply's delivery cue.

        The per-reply cue only changes the *voice* when "adapt delivery"
        (auto_instruct) is on. With it off, the cue is still parsed and used to
        drive VTuber expressions, but the spoken voice stays consistent."""
        base = (CONFIG.tts.instruct or "").strip()
        dyn = (self._turn_instruct or "").strip() if CONFIG.tts.auto_instruct else ""
        if dyn:
            return f"{base}\ndelivery: {dyn}.".strip() if base else f"delivery: {dyn}."
        return base or None

    def _parse_style_stream(self, token_stream):
        """Pull a leading 'VOICE: ...' delivery directive off the token stream,
        store it on self._turn_instruct, and yield the remaining (spoken) text."""
        yield from strip_voice_cue_stream(
            token_stream,
            on_cue=lambda cue: setattr(self, "_turn_instruct", cue),
        )

    def respond(self, user_text: str) -> None:
        corr_id = new_corr_id()
        user_message_id = new_message_id()
        reply_message_id = new_message_id()
        with span(
            "voice.turn",
            corr_id=corr_id,
            user_message_id=user_message_id,
            reply_message_id=reply_message_id,
            user_text_len=len(user_text or ""),
        ) as sp:
            self._respond_turn(
                user_text,
                corr_id=corr_id,
                user_message_id=user_message_id,
                reply_message_id=reply_message_id,
            )
            completion_id = getattr(self.llm, "last_completion_id", None)
            if completion_id and sp is not None and hasattr(sp, "set_attribute"):
                sp.set_attribute("completion_id", str(completion_id))
        record_turn()

    def _respond_turn(
        self,
        user_text: str,
        *,
        corr_id: str,
        user_message_id: str,
        reply_message_id: str,
    ) -> None:
        raw_text = user_text
        user_text = self._interpret_user_turn(user_text)
        if user_text != (raw_text or "").strip():
            log.info("interpreted: %r -> %r", raw_text, user_text)
        display_text = user_text or "[unclear audio]"
        log.info("user: %s", display_text)
        self._emit(type="user", text=display_text, corr_id=corr_id, message_id=user_message_id)
        self.playback.stop()
        self.playback.begin_turn()
        self._barge_in_flag.clear()
        self._pending_user_text = None
        self._turn_instruct = None
        self._expressed = False
        self._avatar_mood_set_this_turn = False
        self._turn_active.set()

        monitor = self._start_barge_listener()

        full_reply = ""
        self._emit(type="status", value="thinking")
        delivery = (CONFIG.tts.delivery or "full").lower()
        try:
            plan: Optional[OrchestratorPlan] = None
            if self._should_orchestrate():
                plan = self._llm_orchestrate(raw_text, user_text)
                if plan and plan.user_meant:
                    if plan.user_meant != (user_text or "").strip():
                        user_text = plan.user_meant
                    self._record_discord_intent_from_text(user_text)

            direct: Optional[str] = None
            if plan and plan.intent not in ("chat", "unknown", "none"):
                direct = self._execute_orchestrator_plan(plan, user_text, raw_text)
            if direct is None:
                direct = self._try_pending_action_direct(user_text)
            if direct is None and not self._maybe_motion_request(
                user_text, plan=plan, raw_text=raw_text,
            ):
                direct = self._try_discord_direct(user_text)
            if direct is None:
                direct = self._try_web_direct(user_text)
            anim_label = self._maybe_play_avatar_animation(
                user_text, plan=plan, raw_text=raw_text,
            )
            if anim_label:
                messages = self._messages_with_animation_hint(user_text, anim_label)
                token_stream = self.llm.stream_messages(messages)
            elif direct is not None:
                self._maybe_emit_avatar_mood(direct)
                token_stream = iter([direct])
            elif self._should_use_tool_loop() and not (
                plan
                and plan.intent == "chat"
                and not self._maybe_motion_request(user_text, plan=plan, raw_text=raw_text)
            ):
                messages = self._build_messages(user_text)
                if _is_weak_transcript(raw_text) or self._has_pending_action():
                    hint = (
                        "[System: speech may be mistranscribed — use recent "
                        "conversation and pending actions to infer intent before "
                        "answering or calling tools.]"
                    )
                    messages[-1]["content"] = f"{hint}\n\n{messages[-1]['content']}"
                result = self.tool_loop.run(messages, emit=self._emit)
                reply_text = result.final_text or ""
                self._maybe_emit_avatar_mood(reply_text)
                token_stream = iter([reply_text])
            else:
                messages = self._build_messages(user_text)
                token_stream = self.llm.stream_messages(messages)
            if CONFIG.wants_style_cue():
                token_stream = self._parse_style_stream(token_stream)
            full_reply = self._deliver(
                delivery,
                token_stream,
                corr_id=corr_id,
                reply_message_id=reply_message_id,
            )

            # Let queued audio finish unless interrupted.
            while self.playback.is_playing() and not self._barge_in_flag.is_set():
                time.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            log.exception("turn failed: %s", exc)
            self._emit(type="error", text=str(exc))
        finally:
            self._turn_active.clear()
            self._stop_barge_listener(monitor)

        if not (full_reply or "").strip() and not self._barge_in_flag.is_set():
            log.warning("empty LLM reply for user turn: %r", display_text[:120])
            self._emit(
                type="error",
                text="No reply from the language model. Check LM Studio has a model loaded.",
            )

        if self._barge_in_flag.is_set():
            self.playback.stop()
            log.info("barge-in stopped speaking")
            self._emit(type="barge_in")

        if self.is_session_running():
            completion_id = getattr(self.llm, "last_completion_id", None)
            listen_ev: dict[str, Any] = {
                "type": "status",
                "value": "listening",
                "corr_id": corr_id,
                "message_id": reply_message_id,
            }
            if completion_id:
                listen_ev["completion_id"] = str(completion_id)
            self._emit(**listen_ev)

        # Record the exchange for context.
        self.history.append(
            {
                "role": "user",
                "content": display_text,
                "message_id": user_message_id,
                "corr_id": corr_id,
            }
        )
        if full_reply:
            completion_id = getattr(self.llm, "last_completion_id", None)
            self.history.append(
                {
                    "role": "assistant",
                    "content": full_reply,
                    "message_id": reply_message_id,
                    "corr_id": corr_id,
                    "completion_id": str(completion_id) if completion_id else None,
                }
            )
            self._maybe_emit_avatar_mood(full_reply)

        # Persist to the session log and let the background review adapt memory.
        if self.memory is not None:
            try:
                turn_scope = self._derive_memory_scope(display_text)
                self.memory.set_turn_scope(turn_scope)
                self.memory.log_turn(display_text, full_reply)
                self.memory.schedule_review(display_text, full_reply, scope=turn_scope)
            except Exception as exc:  # noqa: BLE001
                log.warning("memory turn logging failed: %s", exc)

    def _deliver(
        self,
        delivery: str,
        token_stream,
        *,
        corr_id: str,
        reply_message_id: str,
    ) -> str:
        """Route the LLM token stream to TTS per the delivery mode. Returns the
        full (cleaned) reply text for history."""
        spoke = [False]

        def mark_speaking() -> None:
            if not spoke[0]:
                self._emit(type="status", value="speaking")
                self._emit_tts_info()
                if self._turn_instruct:
                    self._emit(type="delivery", cue=self._turn_instruct)
                spoke[0] = True

        if delivery == "off":
            # Per-sentence: lowest latency, most tone variation.
            parts: list[str] = []
            for chunk in sentence_chunks(token_stream):
                if self._barge_in_flag.is_set():
                    break
                chunk = _clean_text(chunk)
                if not chunk:
                    continue
                parts.append(chunk)
                mark_speaking()
                self._emit(type="ai", text=chunk, corr_id=corr_id, message_id=reply_message_id)
                self._speak(chunk)
            return " ".join(parts)

        if delivery == "hybrid":
            # Speak the first sentence fast, then the remainder as one generation.
            first_spoken = False
            first_text = ""
            rest_parts: list[str] = []
            for chunk in sentence_chunks(token_stream):
                if self._barge_in_flag.is_set():
                    break
                chunk = _clean_text(chunk)
                if not chunk:
                    continue
                self._emit(type="ai", text=chunk, corr_id=corr_id, message_id=reply_message_id)
                if not first_spoken:
                    first_text = chunk
                    mark_speaking()
                    self._speak(chunk)
                    first_spoken = True
                else:
                    rest_parts.append(chunk)
            rest = " ".join(rest_parts)
            if rest and not self._barge_in_flag.is_set():
                self._speak(rest)
            return " ".join(p for p in (first_text, rest) if p)

        # "full" (default): gather the whole reply, synthesize as one generation.
        text = ""
        for token in token_stream:
            if self._barge_in_flag.is_set():
                break
            text += token
        self._apply_pseudo_tool_calls_from_text(text)
        text, _ = finalize_reply_text(text)
        text = _clean_text(text)
        if not text:
            return ""
        self._emit(
            type="ai",
            text=text,
            final=True,
            corr_id=corr_id,
            message_id=reply_message_id,
        )
        mark_speaking()
        self._speak(text)
        return text

    def _on_barge_in(self) -> None:
        self._barge_in_flag.set()
        self.playback.fade_out()         # graceful trail-off instead of hard cut

    # ----- barge-in ---------------------------------------------------------

    def _start_barge_listener(self):
        """Begin listening for an interruption while the agent speaks.

        Returns a BargeInMonitor for "instant" mode, or None for "smart"/"off"
        (smart runs on a tracked thread, off does nothing)."""
        if self.mode != "vad" or not CONFIG.audio.barge_in:
            return None
        mode = (self.barge_mode or "smart").lower()
        if mode == "off":
            return None
        if mode == "instant":
            from vad import BargeInMonitor

            monitor = BargeInMonitor(
                on_barge_in=self._on_barge_in, aec=self.aec, mic=self._mic
            )
            monitor.start()
            return monitor
        return None

    def _stop_barge_listener(self, monitor) -> None:
        if monitor is not None:
            monitor.stop()

    def _duplex_worker(self) -> None:
        """Smart barge-in: listen while the agent speaks, duck, transcribe, queue."""
        from dataclasses import replace

        from vad import (
            barge_speech_detector,
            is_plausible_user_speech,
            record_barge_utterance,
        )

        barge_cfg = replace(
            CONFIG.vad,
            silence_ms=min(CONFIG.vad.silence_ms, 420),
            min_speech_ms=max(200, min(CONFIG.vad.min_speech_ms, 280)),
        )
        from vad import _VADState

        barge_state = _VADState(barge_cfg, CONFIG.stt.sample_rate)
        detect = barge_speech_detector(barge_state, playback_level=self.playback.level)

        def _clean(frame):
            return self.aec.process_frame(frame) if self.aec is not None else frame

        while not self._session_stop.is_set():
            if (
                not self._turn_active.is_set()
                or not self.playback.is_playing()
                or self._barge_in_flag.is_set()
                or not CONFIG.audio.barge_in
                or (self.barge_mode or "smart").lower() != "smart"
                or self._mic is None
                or self.stt is None
                or time.time() < self._barge_cooldown_until
            ):
                time.sleep(0.03)
                continue

            ducked = False

            def on_speech() -> None:
                nonlocal ducked
                if not ducked and self._turn_active.is_set() and not self._barge_in_flag.is_set():
                    ducked = True
                    self.playback.duck(0.06, 80)
                    self._emit(type="status", value="hearing")
                    log.debug("duplex hearing user")

            def done() -> bool:
                return (
                    self._barge_in_flag.is_set()
                    or self._session_stop.is_set()
                    or not self._turn_active.is_set()
                    or not self.playback.is_playing()
                )

            try:
                with self._mic.capture_lock():
                    audio = record_barge_utterance(
                        mic=self._mic,
                        cfg=barge_cfg,
                        is_trigger=detect,
                        should_stop=done,
                        on_speech_start=on_speech,
                        trigger_frames=4,
                        silence_rms=320.0,
                        frame_processor=_clean if self.aec is not None else None,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("duplex capture error: %s", exc)
                time.sleep(0.1)
                continue

            self._barge_cooldown_until = time.time() + 1.5

            if done() and audio.size == 0:
                if ducked:
                    self.playback.unduck(250)
                continue
            if audio.size == 0:
                if ducked:
                    self.playback.unduck(250)
                    log.debug("duplex no utterance captured")
                continue

            if not is_plausible_user_speech(audio, playback_level=self.playback.level):
                if ducked:
                    self.playback.unduck(250)
                log.debug("duplex rejected weak audio")
                continue

            if ducked:
                self.playback.duck(0.04, 60)
            dur = audio.size / CONFIG.stt.sample_rate
            log.debug("duplex captured %.2fs, transcribing", dur)

            text = (self.stt.transcribe_array(audio, CONFIG.stt.sample_rate, barge=True) or "").strip()
            if not _is_barge_transcript(text):
                if ducked:
                    self.playback.unduck(250)
                log.debug("duplex ignored transcript: %r", text)
                if self.aec is not None:
                    self.aec.reset()
                continue

            log.info("user (barge): %s", text)
            self._pending_user_text = text
            self._barge_in_flag.set()
            self.playback.stop()
            self._emit(type="barge_in")

    # ----- live settings (web UI) -------------------------------------------

    def _personality_store(self):
        from memory.personalities import PersonalityStore

        return PersonalityStore(CONFIG.memory.resolve_data_dir())

    def list_personalities(self) -> dict:
        store = self._personality_store()
        active = store.list().get("active") or ""
        detail = store.get(active) if active else None
        return {
            "ok": True,
            **store.list(),
            "card": (detail or {}).get("card"),
            "creator_notes": (detail or {}).get("creator_notes", ""),
            "post_history": (detail or {}).get("post_history", ""),
            "system_prompt": (detail or {}).get("prompt", ""),
        }

    def _apply_personality_state(self, state: dict) -> None:
        prompt = str(state.get("prompt") or "").strip()
        if not prompt:
            return
        from memory.character_card import compile_greeting
        from memory.user_profile import resolve_user_name

        CONFIG.llm.system_prompt = prompt
        self._post_history_instructions = str(state.get("post_history") or "").strip()
        self._active_card = dict(state.get("card") or {})
        self.history.clear()
        user_name = resolve_user_name(CONFIG.memory.resolve_data_dir())
        self._greeting_pending = bool(
            compile_greeting(self._active_card, user_name=user_name),
        )
        if self.memory is not None:
            self._session_prefix = self.memory.system_suffix()
        from memory.personalities import persist_active_personality

        persist_active_personality(
            CONFIG,
            CONFIG.llm.system_prompt,
            card=state.get("card"),
        )
        self._emit(
            type="settings",
            system_prompt=CONFIG.llm.system_prompt,
            post_history=self._post_history_instructions,
            card=state.get("card"),
            creator_notes=state.get("creator_notes", ""),
        )
        if self.is_session_running():
            threading.Thread(
                target=self._deliver_greeting_if_needed,
                name="personality-greeting",
                daemon=True,
            ).start()

    def activate_personality(self, personality_id: str) -> dict:
        res = self._personality_store().activate(personality_id)
        if not res.get("ok"):
            return res
        self._apply_personality_state(res)
        return {"ok": True, **res, "system_prompt": CONFIG.llm.system_prompt}

    def save_personality(
        self,
        name: str,
        prompt: str = "",
        personality_id: str = "",
        card: Optional[dict] = None,
        *,
        activate: bool = True,
    ) -> dict:
        res = self._personality_store().save(
            name, prompt, personality_id, card=card, activate=activate,
        )
        if not res.get("ok"):
            return res
        if activate:
            self._apply_personality_state(res)
        return {
            "ok": True,
            **res,
            "system_prompt": CONFIG.llm.system_prompt,
            **self._personality_store().list(),
        }

    def import_personality(self, raw: dict, *, activate: bool = True) -> dict:
        res = self._personality_store().import_card(raw, activate=activate)
        if not res.get("ok"):
            return res
        if activate:
            self._apply_personality_state(res)
        return {
            "ok": True,
            **res,
            "system_prompt": CONFIG.llm.system_prompt,
            **self._personality_store().list(),
        }

    def import_personality_png(self, png_bytes: bytes, *, activate: bool = True) -> dict:
        from memory.png_card import decode_card_from_png

        try:
            raw = decode_card_from_png(png_bytes)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc)}
        return self.import_personality(raw, activate=activate)

    def build_character_card(self, prompt: str) -> dict:
        from memory.character_builder import build_character_result

        try:
            return build_character_result(self.llm, prompt)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            log.warning("character build failed: %s", exc)
            return {"ok": False, "error": "character generation failed"}

    def export_personality(self, personality_id: str) -> dict:
        return self._personality_store().export_card(personality_id)

    def delete_personality(self, personality_id: str) -> dict:
        res = self._personality_store().delete(personality_id)
        if not res.get("ok"):
            return res
        self._apply_personality_state(res)
        return {
            "ok": True,
            **res,
            "system_prompt": CONFIG.llm.system_prompt,
            **self._personality_store().list(),
        }

    def set_system_prompt(self, prompt: str) -> None:
        """Swap the agent's personality. Clears context so the new persona isn't
        anchored by replies made in the old one."""
        active = self._personality_store().list().get("active") or ""
        entry = self._personality_store().get(active) if active else None
        from memory.character_card import compile_character_prompt
        from memory.user_profile import resolve_user_name

        card = dict((entry or {}).get("card") or {})
        if card:
            card["system_prompt"] = prompt.strip()
            compiled, post = compile_character_prompt(
                card, user_name=resolve_user_name(CONFIG.memory.resolve_data_dir()),
            )
            state = {
                "prompt": compiled,
                "post_history": post,
                "card": card,
                "creator_notes": card.get("creator_notes", ""),
            }
            self._apply_personality_state(state)
            return
        self._post_history_instructions = ""
        CONFIG.llm.system_prompt = prompt.strip()
        self.history.clear()
        if self.memory is not None:
            self._session_prefix = self.memory.system_suffix()
        from memory.personalities import persist_active_personality

        persist_active_personality(CONFIG, CONFIG.llm.system_prompt)
        self._emit(type="settings", system_prompt=CONFIG.llm.system_prompt)

    # ----- memory + tools (web UI) ------------------------------------------

    def memory_status(self) -> dict:
        if self.memory is None:
            return {"enabled": False}
        return self.memory.status()

    def approve_memory(self, sid: str) -> dict:
        if self.memory is None:
            return {"ok": False, "error": "memory disabled"}
        res = self.memory.approve(sid)
        self._emit(type="memory_updated", target="approved")
        return res

    def reject_memory(self, sid: str) -> dict:
        if self.memory is None:
            return {"ok": False, "error": "memory disabled"}
        return self.memory.reject(sid)

    def edit_memory(self, action: str, target: str, content: str = "", old_text: str = "") -> dict:
        """Direct memory edit from the UI (bypasses approval - the user is editing)."""
        if self.memory is None:
            return {"ok": False, "error": "memory disabled"}
        res = self.memory.curated.apply_action(
            {"action": action, "target": target, "content": content, "old_text": old_text})
        self._session_prefix = self.memory.system_suffix()
        return {"ok": bool(res.get("success")), **res}

    def set_write_approval(self, enabled: bool) -> None:
        """Toggle whether memory writes are staged for approval vs applied freely."""
        CONFIG.memory.write_approval = bool(enabled)
        if self.memory is not None:
            self.memory.cfg.write_approval = CONFIG.memory.write_approval
            self.memory.curated.write_approval = CONFIG.memory.write_approval
        self._emit(type="settings", memory_write_approval=CONFIG.memory.write_approval)

    def session_search(self, query: str, limit: int = 8) -> list[dict]:
        if self.memory is None:
            return []
        return self.memory.sessions.search(query, limit)

    def memory_explore(
        self,
        db: str,
        limit: int = 50,
        offset: int = 0,
        session_id: str = "",
        scope: str = "",
    ) -> dict:
        if self.memory is None:
            return {"ok": False, "error": "memory disabled"}
        result = self.memory.explore_db(
            db,
            limit=limit,
            offset=offset,
            session_id=session_id or None,
            scope=scope or None,
        )
        if result.get("error"):
            return {"ok": False, **result}
        return {"ok": True, **result}

    def read_skill(self, name: str) -> dict:
        if self.memory is None:
            return {"ok": False, "error": "memory disabled"}
        content = self.memory.read_skill(name)
        if content is None:
            return {"ok": False, "error": "skill not found"}
        return {"ok": True, "name": name, "content": content}

    def tools_status(self) -> dict:
        return {
            "enabled": self._tools_active(),
            "mode": CONFIG.tools.mode,
            "max_rounds": CONFIG.tools.max_rounds,
            "tools": self.registry.ui_list() if self.registry is not None else [],
            "mcp": self.mcp.status() if self.mcp is not None else {"servers": {}},
        }

    def set_delivery(self, mode: str) -> None:
        mode = (mode or "").lower()
        if mode in {"full", "hybrid", "off"}:
            CONFIG.tts.delivery = mode
            self._emit(type="settings", delivery=mode)

    def set_barge_mode(self, mode: str) -> None:
        mode = (mode or "").lower()
        if mode in {"smart", "instant", "off"}:
            self.barge_mode = mode
            self._emit(type="settings", barge_mode=mode)

    def set_output_volume(self, level: float) -> None:
        CONFIG.audio.output_volume = max(0.0, min(2.0, float(level)))
        self.playback.set_output_volume(CONFIG.audio.output_volume)
        pct = int(round(CONFIG.audio.output_volume * 100))
        self._emit(type="settings", output_volume=CONFIG.audio.output_volume, output_volume_percent=pct)

    def set_output_sink(self, sink: str) -> None:
        mode = "browser" if str(sink or "").strip().lower() == "browser" else "system"
        CONFIG.audio.output_sink = mode
        self.playback.set_output_sink(mode)
        self._emit(type="settings", output_sink=mode)

    def set_discord_music_volume(self, level: float) -> None:
        CONFIG.discord.music_volume = max(0.0, min(2.0, float(level)))
        if self.discord is not None:
            try:
                self.discord.set_music_volume(CONFIG.discord.music_volume)
            except Exception:  # noqa: BLE001
                pass
        pct = int(round(CONFIG.discord.music_volume * 100))
        self._emit(type="settings", discord_music_volume=CONFIG.discord.music_volume,
                   discord_music_volume_percent=pct)

    def set_instruct(self, text: str) -> None:
        """Set the natural-language voice description (how the speech should sound:
        pitch, speed, emotion, etc.). Applies to every subsequent generation."""
        CONFIG.tts.instruct = (text or "").strip()
        self._emit(type="settings", instruct=CONFIG.tts.instruct)

    def set_auto_instruct(self, enabled: bool) -> None:
        """Toggle per-reply auto-delivery (LLM picks whisper/laugh/etc. each turn).
        This only affects the *voice*; VTuber expressions are controlled
        separately by set_auto_express()."""
        CONFIG.tts.auto_instruct = bool(enabled)
        self._emit(type="settings", auto_instruct=CONFIG.tts.auto_instruct)

    def set_auto_express(self, enabled: bool) -> None:
        """Toggle auto VTuber expressions (emotion-driven faces/animations)."""
        CONFIG.vts.expressions = bool(enabled)
        self._emit(type="settings", auto_express=CONFIG.vts.expressions)
        self._emit(type="vts", **self.vts_status())

    def set_eq_enabled(self, enabled: bool) -> None:
        CONFIG.audio.eq_enabled = bool(enabled)
        self.playback.set_eq_enabled(CONFIG.audio.eq_enabled)
        st = self.playback.eq_status()
        self._emit(type="settings", eq_enabled=CONFIG.audio.eq_enabled,
                   eq_preset=st.get("preset"), eq_bands=st.get("bands", []))

    def set_eq_preset(self, preset: str) -> None:
        from eq import EQ_PRESET_LABELS

        preset = (preset or "off").lower()
        if preset not in EQ_PRESET_LABELS:
            preset = "off"
        CONFIG.audio.eq_preset = preset
        self.playback.set_eq_preset(preset)
        self._emit(type="settings", eq_preset=preset, eq_bands=self.playback.eq_status().get("bands", []))

    def set_eq_custom_bands(self, bands: list[dict]) -> None:
        CONFIG.audio.eq_preset = "custom"
        self.playback.set_eq_custom_bands(bands)
        st = self.playback.eq_status()
        self._emit(type="settings", eq_preset="custom", eq_bands=st.get("bands", []))

    def set_xvec_only(self, enabled: bool) -> None:
        """Toggle x-vector-only cloning. False = full ICL (stronger instruct/likeness,
        may bleed the reference clip); True = embedding only (no bleed).

        Turning ICL on needs a reference transcript, so auto-transcribe one if the
        current voice doesn't have it yet."""
        CONFIG.tts.xvec_only = bool(enabled)
        self.voice.cfg.xvec_only = bool(enabled)
        if not enabled:
            self._ensure_icl_ref_text()
        else:
            sync_clone_ref_text(CONFIG.tts)
        clear_voice_prompt_cache(getattr(self.voice, "model", None))
        self._emit(type="settings", xvec_only=CONFIG.tts.xvec_only)

    def _ensure_stt_for_ref_text(self) -> None:
        """Load STT on demand so reference clips can be transcribed for ICL mode."""
        if self.stt is not None:
            return
        from stt import create_stt

        log.info("loading STT for reference transcription (%s)", CONFIG.stt.whisper_model)
        self.stt = create_stt()

    def _ensure_icl_ref_text(self) -> None:
        """Ensure ref_text exists when ICL clone mode is active (auto-transcribe if needed)."""
        if CONFIG.tts.xvec_only or self.voice is None:
            return
        ref = CONFIG.tts.ref_audio
        if not ref or not os.path.exists(ref):
            return
        sync_clone_ref_text(CONFIG.tts)
        if CONFIG.tts.ref_text.strip():
            self.voice.cfg.ref_text = CONFIG.tts.ref_text.strip()
            return
        self._ensure_stt_for_ref_text()
        log.info("no ref transcript for %s — transcribing on first speak", os.path.basename(ref))
        text = self.ensure_ref_text(ref)
        if text:
            CONFIG.tts.ref_text = text
            self.voice.cfg.ref_text = text
            clear_voice_prompt_cache(getattr(self.voice, "model", None))

    # ----- VTuber (VTube Studio) -------------------------------------------

    def _start_vtuber(self) -> None:
        if self.vtuber is not None:
            return
        try:
            from vtuber import VTubeStudioClient

            self.vtuber = VTubeStudioClient(on_event=self._emit_raw)
            # Lip-sync reads the live playback amplitude.
            self.vtuber.start(level_fn=self.playback.level)
            log.info("VTuber support enabled; connecting to VTube Studio")
        except Exception as exc:  # noqa: BLE001
            self.vtuber = None
            log.warning("could not start VTuber support: %s", exc)

    def _stop_vtuber(self) -> None:
        if self.vtuber is not None:
            try:
                self.vtuber.close()
            except Exception:  # noqa: BLE001
                pass
            self.vtuber = None

    def set_vts_enabled(self, enabled: bool) -> None:
        CONFIG.vts.enabled = bool(enabled)
        if enabled:
            self._start_vtuber()
        else:
            self._stop_vtuber()
        self._emit(type="settings", vts_enabled=CONFIG.vts.enabled)
        self._emit(type="vts", **self.vts_status())

    def vts_status(self) -> dict:
        if self.vtuber is None:
            return {"enabled": CONFIG.vts.enabled, "connected": False,
                    "authenticated": False, "hotkeys": [], "expressions": [],
                    "actions": [], "emotions": [], "emotions_list": [],
                    "map": {}, "last_expression": None}
        return self.vtuber.status()

    def set_vts_map(self, mapping: dict) -> dict:
        """Update the emotion -> action mapping (and persist it)."""
        if self.vtuber is None:
            return self.vts_status()
        self.vtuber.set_emotion_map(mapping)
        return self.vts_status()

    def test_vts_action(self, name: str) -> bool:
        """Fire a hotkey/expression by name so the user can preview it."""
        if self.vtuber is None:
            return False
        return self.vtuber.test_action(name)

    def _emit_raw(self, event: dict) -> None:
        """Pass a pre-built event dict straight through to the UI broadcaster."""
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:  # noqa: BLE001
                pass

    def _express(self, *texts: str) -> None:
        """Trigger a VTuber expression for this reply (once per turn)."""
        if self.vtuber is None or self._expressed:
            return
        from vtuber import detect_emotion

        emotion = detect_emotion(*texts)
        fired = self.vtuber.trigger_emotion(emotion)
        self._expressed = True
        if fired:
            self._emit(type="expression", emotion=fired)

    def ensure_ref_text(self, path: str) -> str:
        """Return the reference transcript for clip `path`, creating a '<name>.txt'
        sidecar by transcribing the clip if one doesn't already exist (cached for
        next time). Returns '' if STT is unavailable or transcription fails."""
        sidecar = os.path.splitext(path)[0] + ".txt"
        if os.path.exists(sidecar):
            try:
                with open(sidecar, encoding="utf-8") as fh:
                    return fh.read().strip()
            except OSError:
                pass
        self._ensure_stt_for_ref_text()
        if self.stt is None:
            return ""
        log.info("transcribing reference for ICL: %s", os.path.basename(path))
        try:
            text = (self.stt.transcribe_file(path) or "").strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("reference transcription failed: %s", exc)
            return ""
        if text:
            try:
                with open(sidecar, "w", encoding="utf-8") as fh:
                    fh.write(text)
                log.info("saved transcript -> %s", os.path.basename(sidecar))
            except OSError:
                pass
        return text

    def _deliver_greeting_if_needed(self) -> None:
        """Speak first_mes when a session starts or personality changes."""
        with self._greeting_lock:
            if not self._greeting_pending or self.history:
                self._greeting_pending = False
                return
            from memory.character_card import compile_greeting
            from memory.user_profile import resolve_user_name

            user_name = resolve_user_name(CONFIG.memory.resolve_data_dir())
            text = compile_greeting(self._active_card, user_name=user_name)
            self._greeting_pending = False
            if not text:
                return
            self.history.append({"role": "assistant", "content": text})
            if self.memory is not None:
                try:
                    self.memory.sessions.log("assistant", text)
                except Exception:  # noqa: BLE001
                    pass
        cleaned = _clean_text(text)
        if cleaned:
            self._emit(type="ai", text=cleaned, final=True)
        self._emit(type="status", value="speaking")
        self._emit_tts_info()
        self._speak(text)
        while self.playback.is_playing() and not self._session_stop.is_set():
            time.sleep(0.05)
        if self.is_session_running():
            self._emit(type="status", value="listening")

    # ----- web session control ---------------------------------------------

    def is_session_running(self) -> bool:
        return self._session_thread is not None and self._session_thread.is_alive()

    def start_session(self) -> None:
        """Start a hands-free VAD conversation loop on a background thread."""
        if self.is_session_running():
            return
        if self.stt is None:
            from stt import create_stt

            log.info("loading STT (faster-whisper %s)", CONFIG.stt.whisper_model)
            self.stt = create_stt()
        self._session_stop.clear()
        from vad import SharedMic

        if self._mic is None:
            self._mic = SharedMic()
            self._mic.start()
            log.info("session mic open (full-duplex)")
        if self._duplex_thread is None or not self._duplex_thread.is_alive():
            self._duplex_thread = threading.Thread(target=self._duplex_worker, daemon=True)
            self._duplex_thread.start()
            log.info("session duplex barge listener started")
        self._session_thread = threading.Thread(target=self._vad_session, daemon=True)
        self._session_thread.start()

    def stop_session(self) -> None:
        self._session_stop.set()
        self._barge_in_flag.set()
        self._turn_active.clear()
        self.playback.stop()
        thread = self._session_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._session_thread = None
        duplex = self._duplex_thread
        if duplex is not None and duplex is not threading.current_thread():
            duplex.join(timeout=2.0)
        self._duplex_thread = None
        if self._mic is not None:
            self._mic.stop()
            self._mic = None
            log.info("session mic closed")
        self._emit(type="status", value="idle")

    def _vad_session(self) -> None:
        from vad import record_until_silence

        self._deliver_greeting_if_needed()
        self._emit(type="status", value="listening")
        pending: Optional[str] = None
        try:
            while not self._session_stop.is_set():
                if pending:
                    text, pending = pending, None
                else:
                    self._emit(type="status", value="listening")

                    def _process_idle(f):
                        return self.aec.process_frame(f) if self.aec is not None else f

                    with self._mic.capture_lock():
                        self._mic.flush()
                        audio = record_until_silence(
                            on_speech_start=lambda: self._emit(type="status", value="hearing"),
                            should_stop=self._session_stop.is_set,
                            mic=self._mic,
                            frame_processor=_process_idle if self.aec is not None else None,
                        )
                    if self._session_stop.is_set():
                        break
                    if audio.size == 0:
                        continue
                    self._emit(type="status", value="transcribing")
                    text = (self.stt.transcribe_array(audio, CONFIG.stt.sample_rate) or "").strip()
                    if not text:
                        if (
                            self._has_pending_action()
                            or self._last_discord_intent
                        ):
                            text = ""
                        else:
                            continue
                self.respond(text)
                if self._pending_user_text:
                    pending = self._pending_user_text
                    self._pending_user_text = None
        except Exception as exc:  # noqa: BLE001
            self._emit(type="error", text=str(exc))
        finally:
            self._emit(type="status", value="idle")

    # ----- input loops ------------------------------------------------------

    def run_typed(self) -> None:
        while True:
            try:
                text = input("\nSay/type something: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in {"q", "quit", "exit"}:
                break
            if text:
                self.respond(text)

    def run_ptt(self) -> None:
        from vad import record_fixed

        while True:
            try:
                cmd = input(f"\n[Enter] to record {self.ptt_seconds:.0f}s (q to quit): ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if cmd.lower() in {"q", "quit", "exit"}:
                break
            log.info("recording")
            audio = record_fixed(self.ptt_seconds, CONFIG.stt.sample_rate)
            text = self.stt.transcribe_array(audio, CONFIG.stt.sample_rate)
            if not text:
                log.info("stt heard nothing, try again")
                continue
            self.respond(text)

    def run_vad(self) -> None:
        from vad import record_until_silence

        log.info("hands-free mode — Ctrl+C to quit")
        while True:
            try:
                audio = record_until_silence(on_speech_start=lambda: log.debug("listening"))
            except KeyboardInterrupt:
                break
            if audio.size == 0:
                continue
            text = self.stt.transcribe_array(audio, CONFIG.stt.sample_rate)
            if not text:
                continue
            self.respond(text)

    def run(self) -> None:
        try:
            if self.mode == "typed":
                self.run_typed()
            elif self.mode == "ptt":
                self.run_ptt()
            elif self.mode == "vad":
                self.run_vad()
            else:
                raise ValueError(f"Unknown mode: {self.mode}")
        finally:
            if self.discord is not None:
                self.discord.close()
            if self.mcp is not None:
                self.mcp.close()
            self.playback.close()
