"""Voice agent hub — per-operator context, voice lease, room support."""

from __future__ import annotations

import os
import queue
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from server import Hub

from services.ids import new_corr_id, new_message_id
from services.llm.provider import create_llm_client, is_webllm_provider, swap_agent_llm
from services.operator_voice.paths import operator_data_dir as op_data_dir
from services.paths import DATA_DIR, VOICE_RUNTIME
from services.voice.data_migration import migrate_qwen3_data_to_unified
from services.settings.store import (
    apply_to_config,
    load_effective_settings,
    load_settings as load_global_settings,
    save_settings as save_global_settings,
    seed_env_defaults,
)

_RELOAD_SECTIONS = frozenset({"discord", "tools", "memory", "runtime"})
_llm_lock = threading.Lock()
_tts_lock = threading.Lock()

try:
    from observability import get_logger, span
except ImportError:  # pragma: no cover
    import logging
    from contextlib import contextmanager

    get_logger = logging.getLogger

    @contextmanager
    def span(*_args, **_kwargs):
        yield None


log = get_logger("maya-unified.hub")

from services.voice.inference import INFERENCE_LOCK as _inference_lock


def _chat_event(
    base: dict,
    *,
    corr_id: str,
    message_id: str | None = None,
    completion_id: str | None = None,
) -> dict:
    ev = {**base, "corr_id": corr_id}
    if message_id:
        ev["message_id"] = message_id
    if completion_id:
        ev["completion_id"] = completion_id
    return ev


def _llm_completion_id(llm: Any) -> str | None:
    cid = getattr(llm, "last_completion_id", None)
    return str(cid) if cid else None


def _voice_cue_filtered_stream(stream):
    """Strip leading VOICE: delivery cues from an LLM token stream when enabled."""
    from agent import strip_voice_cue_stream
    from config import CONFIG

    if CONFIG.wants_style_cue():
        return strip_voice_cue_stream(stream)
    return stream


def _publish_ai_reply(hub: "VoiceHub", raw: str, *, operator_id: str | None = None, room_id: str | None = None) -> str:
    """Strip VOICE: cues and broadcast one clean assistant turn."""
    from agent import finalize_reply_text

    reply, cue = finalize_reply_text(raw)
    if reply:
        hub.broadcast({"type": "ai", "text": reply}, operator_id=operator_id, room_id=room_id)
    if cue:
        hub.broadcast({"type": "delivery", "cue": cue}, operator_id=operator_id, room_id=room_id)
    return reply


@dataclass
class VoiceLease:
    kind: str  # "operator" | "room"
    context_id: str
    speaker_id: str | None = None
    speaker_name: str | None = None


@dataclass
class _Subscriber:
    q: queue.Queue
    operator_id: str | None = None
    room_id: str | None = None


def _nested_get(data: dict, *keys: str):
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _nested_changed(previous: dict, merged: dict, *keys: str) -> bool:
    return _nested_get(previous, *keys) != _nested_get(merged, *keys)


def _section_changed(previous: dict, merged: dict, section: str) -> bool:
    return (previous or {}).get(section) != (merged or {}).get(section)


_TTS_ENGINE_KEYS = (
    ("voice", "clone_model"),
    ("voice", "custom_model"),
    ("voice", "device"),
    ("delivery", "tts_mode"),
)


def _tts_engine_changed(previous: dict, merged: dict) -> bool:
    """TTS weights/mode are loaded once at agent start — require reload to apply."""
    return any(_nested_changed(previous, merged, *keys) for keys in _TTS_ENGINE_KEYS)


def _mirror_operator_runtime_globals(previous: dict, merged: dict) -> None:
    """Mirror voice/TTS fields to settings.json so cold start matches operator picks."""
    if _section_changed(previous, merged, "voice"):
        voice = merged.get("voice")
        if isinstance(voice, dict):
            save_global_settings({"voice": voice})
    if _section_changed(previous, merged, "delivery"):
        delivery = merged.get("delivery")
        if isinstance(delivery, dict):
            save_global_settings({"delivery": delivery})


def _settings_broadcast_payload(merged: dict) -> dict:
    """SSE payload for settings changes — includes vrm subset for avatar hot reload."""
    payload: dict[str, Any] = {"type": "settings", "unified": merged}
    vrm = merged.get("vrm")
    if isinstance(vrm, dict):
        payload["vrm"] = vrm
    return payload


def _build_live_diff(previous: dict, merged: dict) -> dict:
    live: dict = {}
    if _nested_changed(previous, merged, "audio", "eq_preset"):
        preset = _nested_get(merged, "audio", "eq_preset")
        if preset:
            live["eq_preset"] = str(preset)
    if _nested_changed(previous, merged, "audio", "eq_enabled"):
        live["eq_enabled"] = bool(_nested_get(merged, "audio", "eq_enabled"))
    if _nested_changed(previous, merged, "audio", "output_volume"):
        live["output_volume"] = float(_nested_get(merged, "audio", "output_volume") or 1.0)
    if _nested_changed(previous, merged, "audio", "output_sink"):
        sink = _nested_get(merged, "audio", "output_sink")
        if sink:
            live["output_sink"] = str(sink)
    if _nested_changed(previous, merged, "detection", "barge_mode"):
        mode = _nested_get(merged, "detection", "barge_mode")
        if mode:
            live["barge_mode"] = str(mode)
    if _nested_changed(previous, merged, "delivery", "delivery"):
        val = _nested_get(merged, "delivery", "delivery")
        if val:
            live["delivery"] = str(val)
    if _nested_changed(previous, merged, "delivery", "auto_instruct"):
        live["auto_instruct"] = bool(_nested_get(merged, "delivery", "auto_instruct"))
    if _nested_changed(previous, merged, "delivery", "xvec_only"):
        live["xvec_only"] = bool(_nested_get(merged, "delivery", "xvec_only"))
    if _nested_changed(previous, merged, "delivery", "instruct"):
        live["instruct"] = str(_nested_get(merged, "delivery", "instruct") or "")
    if _nested_changed(previous, merged, "vts", "enabled"):
        live["vts_enabled"] = bool(_nested_get(merged, "vts", "enabled"))
    if _nested_changed(previous, merged, "vts", "auto_express"):
        live["auto_express"] = bool(_nested_get(merged, "vts", "auto_express"))
    return live


def _ping_llm(base_url: str, api_key: str, timeout: float = 2.5) -> tuple[bool, str]:
    base = (base_url or "").rstrip("/")
    if not base:
        return False, "LLM base URL is empty — set it in Settings → Reasoning"
    url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key or 'lm-studio'}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False, f"LLM server returned HTTP {resp.status}"
            return True, ""
    except urllib.error.URLError:
        return False, (
            f"Cannot reach LLM at {base}. "
            "Start LM Studio and load a model, or update Settings → Reasoning."
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


class VoiceHub(Hub):
    last_error: str = ""
    voice_lease: VoiceLease | None = None
    _active_operator_id: str | None = None
    _active_room_id: str | None = None
    _scoped_subscribers: list[_Subscriber]

    def __init__(self) -> None:
        super().__init__()
        self._scoped_subscribers = []

    # ----- SSE with operator/room scoping -----------------------------------

    def subscribe(self, operator_id: str | None = None, room_id: str | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        sub = _Subscriber(q=q, operator_id=operator_id, room_id=room_id)
        with self._lock:
            self._scoped_subscribers.append(sub)
            self._subscribers.add(q)
        q.put({"type": "status", "value": self.status})
        q.put({"type": "ready", "value": self.ready})
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)
            self._scoped_subscribers = [s for s in self._scoped_subscribers if s.q is not q]
        super().unsubscribe(q)

    def broadcast(self, event: dict, *, operator_id: str | None = None, room_id: str | None = None) -> None:
        if event.get("type") == "status":
            self.status = event.get("value", self.status)
        ev_op = operator_id or event.get("operator_id")
        ev_room = room_id or event.get("room_id")
        if ev_op and "operator_id" not in event:
            event = {**event, "operator_id": ev_op}
        if ev_room and "room_id" not in event:
            event = {**event, "room_id": ev_room}
        with self._lock:
            subs = list(self._scoped_subscribers)
        global_types = frozenset({"ready", "status", "error", "audio", "audio_begin", "audio_stop"})
        for sub in subs:
            if ev_room:
                if sub.room_id and sub.room_id != ev_room:
                    continue
            elif ev_op:
                if sub.operator_id and sub.operator_id != ev_op:
                    if sub.room_id:
                        continue
                    if event.get("type") not in global_types:
                        continue
            sub.q.put(event)

    def lease_status(self) -> dict[str, Any]:
        if self.voice_lease is None:
            return {"voice_available": True, "voice_owner": None}
        return {
            "voice_available": False,
            "voice_owner": {
                "kind": self.voice_lease.kind,
                "context_id": self.voice_lease.context_id,
                "speaker_id": self.voice_lease.speaker_id,
                "speaker_name": self.voice_lease.speaker_name,
            },
        }

    def _acquire_lease(self, lease: VoiceLease) -> dict:
        if self.voice_lease and (
            self.voice_lease.kind != lease.kind or self.voice_lease.context_id != lease.context_id
        ):
            return {
                "ok": False,
                "error": "voice_in_use",
                "owner": {
                    "kind": self.voice_lease.kind,
                    "context_id": self.voice_lease.context_id,
                    "speaker_name": self.voice_lease.speaker_name,
                },
            }
        self.voice_lease = lease
        return {"ok": True}

    def _release_lease(self, *, kind: str, context_id: str, speaker_id: str | None = None) -> dict:
        if self.voice_lease is None:
            return {"ok": True}
        if self.voice_lease.kind != kind or self.voice_lease.context_id != context_id:
            return {"ok": False, "error": "not_voice_owner"}
        if speaker_id and self.voice_lease.speaker_id and self.voice_lease.speaker_id != speaker_id:
            return {"ok": False, "error": "not_voice_owner"}
        self.voice_lease = None
        return {"ok": True}

    # ----- Operator / room context ------------------------------------------

    def apply_operator_context(self, operator_id: str) -> None:
        from services.operator_voice.paths import (
            load_operator_personalities_file,
            seed_operator_dirs,
        )

        seed_operator_dirs(operator_id)
        data_dir = op_data_dir(operator_id)
        os.environ["VA_DATA_DIR"] = str(data_dir)
        settings = load_effective_settings(operator_id)
        apply_to_config(settings, operator_id=operator_id)
        if self.ready and self.agent is not None:
            from config import CONFIG

            self.agent.playback.set_output_sink(CONFIG.audio.output_sink)
        self._active_operator_id = str(operator_id)
        self._active_room_id = None
        pers = load_operator_personalities_file(operator_id)
        active = str(pers.get("active") or "")
        if active and self.ready and self.agent is not None:
            try:
                self.agent.activate_personality(active)
            except Exception:  # noqa: BLE001
                pass

    def apply_room_context(self, room_id: str, snapshot: dict[str, Any]) -> None:
        from services.operator_voice.paths import room_data_dir

        data_dir = room_data_dir(room_id)
        os.environ["VA_DATA_DIR"] = str(data_dir)
        settings = snapshot.get("settings") or {}
        if settings:
            apply_to_config(settings)
        personality = snapshot.get("personality") or {}
        entry = personality.get("entry") or {}
        prompt = entry.get("prompt") or entry.get("card", {}).get("system_prompt")
        if prompt and self.ready and self.agent is not None:
            from config import CONFIG

            CONFIG.llm.system_prompt = str(prompt)
        self._active_room_id = str(room_id)

    # ----- Lifecycle --------------------------------------------------------

    def unload_agent(self) -> None:
        agent = self.agent
        if agent is not None and getattr(agent, "discord", None) is not None:
            try:
                agent.discord.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.stop(operator_id=self._active_operator_id or "")
        except Exception:  # noqa: BLE001
            pass
        self.agent = None
        self.ready = False
        self.status = "idle"
        self.voice_lease = None
        self.broadcast({"type": "ready", "value": False})

    def request_agent_reload(self) -> None:
        self.unload_agent()
        self.broadcast({"type": "status", "value": "loading"})
        threading.Thread(target=self.load_agent, daemon=True, name="voice-agent-reload").start()

    def load_agent(self) -> None:
        if self.agent is not None and self.ready:
            return
        try:
            self.last_error = ""
            migrate_qwen3_data_to_unified()
            os.makedirs(DATA_DIR, exist_ok=True)
            settings = load_effective_settings(self._active_operator_id)
            apply_to_config(settings)
            from services.discord.unified_bot import apply_discord_env

            apply_discord_env(settings)
            os.environ["VA_DATA_DIR"] = str(DATA_DIR)

            from agent import VoiceAgent

            self.broadcast({"type": "status", "value": "loading"})
            agent = VoiceAgent(mode="vad", on_event=self._agent_event)
            swap_agent_llm(agent)
            self.agent = agent
            from services.discord.patch_agent import patch_voice_agent

            patch_voice_agent(agent)
            from config import CONFIG

            agent.playback.set_output_sink(CONFIG.audio.output_sink)
            self.current_voice = os.path.basename(CONFIG.tts.ref_audio)
            self.ready = True
            self._apply_voice_settings_hot_swap(settings)
            self.broadcast({"type": "ready", "value": True})
            if agent.voice is not None and not getattr(agent.voice, "available", True):
                reason = getattr(agent.voice, "degrade_reason", "TTS unavailable")
                self.broadcast(
                    {
                        "type": "tts_degraded",
                        "text": (
                            "Voice output unavailable — text chat and Discord still work. "
                            f"{reason}"
                        ),
                    }
                )
            self.broadcast({"type": "status", "value": "idle"})
        except Exception as exc:  # noqa: BLE001
            self.ready = False
            self.last_error = str(exc)
            self.broadcast({"type": "error", "text": f"Failed to load agent: {exc}"})
            self.broadcast({"type": "status", "value": "error"})

    def _agent_event(self, event: dict) -> None:
        # PCM chunks must reach every dashboard tab for the active operator.
        if event.get("type") in ("audio", "audio_begin", "audio_stop"):
            op = self._active_operator_id
            self.broadcast(event, operator_id=op, room_id=None)
            return
        op = self._active_operator_id
        room = self._active_room_id
        self.broadcast(event, operator_id=op, room_id=room)

    def apply_settings_patch(self, patch: dict, operator_id: str | None = None) -> dict:
        from services.operator_voice import context as op_ctx

        if operator_id:
            self.apply_operator_context(operator_id)
            previous = op_ctx.load_settings(operator_id)
            merged = op_ctx.save_settings(operator_id, patch if isinstance(patch, dict) else {})
        else:
            previous = load_global_settings()
            merged = save_global_settings(patch if isinstance(patch, dict) else {})
        if merged == previous:
            return merged

        if operator_id:
            _mirror_operator_runtime_globals(previous, merged)

        apply_to_config(merged, operator_id=operator_id)
        from services.discord.unified_bot import apply_discord_env

        apply_discord_env(merged)
        if _section_changed(previous, merged, "reasoning"):
            from services.llm.health import invalidate_llm_health_cache

            invalidate_llm_health_cache()
        needs_reload = any(_section_changed(previous, merged, s) for s in _RELOAD_SECTIONS)
        tts_reload = _tts_engine_changed(previous, merged)
        if (needs_reload or tts_reload) and (self.ready or self.agent is not None):
            self.request_agent_reload()
            self.broadcast(_settings_broadcast_payload(merged), operator_id=operator_id)
            return merged
        if self.ready and self.agent is not None:
            if operator_id:
                self.apply_operator_context(operator_id)
            from config import CONFIG

            self.agent.playback.set_output_sink(CONFIG.audio.output_sink)
            if _section_changed(previous, merged, "reasoning"):
                swap_agent_llm(self.agent)
            if _section_changed(previous, merged, "voice"):
                self._apply_voice_settings_hot_swap(merged)
            live = _build_live_diff(previous, merged)
            if live:
                self.set_config(live)
            new_pid = str(_nested_get(merged, "personality", "active_id") or "")
            old_pid = str(_nested_get(previous, "personality", "active_id") or "")
            if new_pid and new_pid != old_pid:
                self.activate_personality(new_pid)
        self.broadcast(_settings_broadcast_payload(merged), operator_id=operator_id)
        return merged

    def get_config(self, operator_id: str | None = None) -> dict:
        out = super().get_config()
        out["unified_settings"] = load_effective_settings(operator_id or None)
        if self.last_error:
            out["agent_error"] = self.last_error
        out.update(self.lease_status())
        return out

    def conversation_state(self, operator_id: str | None = None) -> dict:
        if operator_id:
            from services.operator_voice import context as op_ctx

            turns = op_ctx.get_conversation(operator_id)
            session_running = bool(
                self.voice_lease
                and self.voice_lease.kind == "operator"
                and self.voice_lease.context_id == str(operator_id)
                and self.ready
                and self.agent
                and self.agent.is_session_running()
            )
            return {
                "ok": True,
                "session_running": session_running,
                "status": self.status,
                "turns": turns,
                **self.lease_status(),
            }
        if not self.ready or self.agent is None:
            return {"ok": True, "session_running": False, "status": self.status, "turns": [], **self.lease_status()}
        turns: list[dict] = []
        for msg in self.agent.history:
            role = msg.get("role")
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            turn: dict[str, Any] = {"text": content}
            if msg.get("message_id"):
                turn["message_id"] = msg["message_id"]
            if msg.get("corr_id"):
                turn["corr_id"] = msg["corr_id"]
            if msg.get("completion_id"):
                turn["completion_id"] = msg["completion_id"]
            if role == "user":
                turn["role"] = "operator"
                turns.append(turn)
            elif role == "assistant":
                turn["role"] = "maya"
                turns.append(turn)
        return {
            "ok": True,
            "session_running": self.agent.is_session_running(),
            "status": self.status,
            "turns": turns,
            **self.lease_status(),
        }

    def _reasoning_settings(self, operator_id: str | None = None) -> dict:
        settings = load_effective_settings(operator_id)
        return settings.get("reasoning", {}) or {}

    def agent_capabilities(self, operator_id: str | None = None) -> dict[str, Any]:
        from services.llm.health import build_agent_capabilities, get_cached_llm_health

        reasoning = self._reasoning_settings(operator_id)
        provider = str(reasoning.get("provider", "lm_studio")).lower()
        if provider == "webllm":
            from services.llm import webllm_broker

            webllm = reasoning.get("webllm") or {}
            browser_ready = webllm_broker.browser_ready()
            health = {
                "status": "ok" if browser_ready else "skipped",
                "provider": "webllm",
                "model": str(webllm.get("model_id") or ""),
                "detail": None if browser_ready else "Keep this dashboard open — WebLLM loads in the browser.",
                "latency_ms": None,
                "models_found": 0,
            }
            caps = build_agent_capabilities(self.ready, health)
            # WebLLM chat is routed through the voice agent bridge, not server-side LLM.
            caps["text_chat"] = self.ready and browser_ready
            caps["text_chat_enriched"] = caps["text_chat"]
            return {"health": health, "capabilities": caps, "llm_ready": caps["text_chat"]}
        else:
            health = get_cached_llm_health(reasoning if isinstance(reasoning, dict) else {})
        caps = build_agent_capabilities(self.ready, health)
        return {"health": health, "capabilities": caps, "llm_ready": caps["text_chat"]}

    def llm_status(self, operator_id: str | None = None) -> dict:
        from config import CONFIG

        snap = self.agent_capabilities(operator_id)
        health = snap["health"]
        reasoning = self._reasoning_settings(operator_id)
        provider = str(reasoning.get("provider", "lm_studio"))
        if provider == "webllm":
            return {
                "ok": snap["llm_ready"],
                "provider": "webllm",
                "base_url": None,
                "model": health.get("model") or "",
                "error": None if snap["llm_ready"] else health.get("detail"),
            }
        return {
            "ok": snap["llm_ready"],
            "provider": provider,
            "base_url": CONFIG.llm.base_url,
            "model": health.get("model") or CONFIG.llm.model,
            "error": None if snap["llm_ready"] else (health.get("detail") or "LLM unavailable"),
        }

    def set_voice(self, path: str, *, warm: bool = True) -> dict:
        """Hot-swap clone reference clip — serialized with LLM/TTS inference."""
        with _inference_lock:
            result = super().set_voice(path, warm=warm)
        if result.get("ok"):
            self._persist_voice_ref(path)
        return result

    @staticmethod
    def _voice_ref_basename(path: str) -> str:
        return os.path.basename((path or "").replace("\\", "/")).lower()

    def _persist_voice_ref(self, path: str, *, operator_id: str | None = None) -> None:
        """Keep settings.json (and operator row) aligned with the active clone clip."""
        base = self._voice_ref_basename(path)
        if not base:
            return
        voice_patch = {"voice": {"ref_audio": f"voices/{base}"}}
        save_global_settings(voice_patch)
        oid = operator_id or self._active_operator_id
        if oid:
            from services.operator_voice import context as op_ctx

            op_ctx.save_settings(oid, voice_patch)
        apply_to_config(load_effective_settings(oid))

    def _apply_voice_settings_hot_swap(self, settings: dict) -> None:
        """Keep the loaded TTS model aligned with saved voice settings."""
        import logging

        from config import CONFIG

        from services.paths import resolve_voice_ref

        log = logging.getLogger("maya-unified.voice")
        voice = settings.get("voice") or {}
        ref = str(voice.get("ref_audio") or "").strip()
        if not ref:
            return
        path = resolve_voice_ref(ref)
        if not path or not os.path.isfile(path):
            log.warning("voice settings ref not found: %s", ref)
            return
        current = ""
        if self.agent is not None and getattr(self.agent, "voice", None) is not None:
            current = str(getattr(self.agent.voice.cfg, "ref_audio", "") or "")
        if self._voice_ref_basename(path) == self._voice_ref_basename(current):
            return
        warm = bool(voice.get("warmup", CONFIG.tts.warmup))
        result = self.set_voice(path, warm=warm)
        if not result.get("ok"):
            log.warning("voice settings hot-swap failed: %s", result.get("error"))

    def _chat_text_basic(self, text: str, operator_id: str | None = None) -> dict:
        """Text chat via create_llm_client when VoiceAgent is still loading."""
        from config import CONFIG

        from services.llm.health import get_cached_llm_health, llm_ready_from_health
        from services.llm.provider import create_llm_client

        reasoning = self._reasoning_settings(operator_id)
        provider = str(reasoning.get("provider", "lm_studio")).lower()
        if provider == "webllm":
            return {
                "ok": False,
                "error": "WebLLM runs in the browser — use the Conversation page with WebLLM enabled.",
            }
        if operator_id:
            self.apply_operator_context(operator_id)
        apply_to_config({"reasoning": reasoning})
        health = get_cached_llm_health(reasoning, run_probe=True)
        if not llm_ready_from_health(health):
            return {"ok": False, "error": health.get("detail") or "LLM unavailable"}
        try:
            corr_id = new_corr_id()
            user_message_id = new_message_id()
            reply_message_id = new_message_id()
            client = create_llm_client()
            with span(
                "chat.corr",
                corr_id=corr_id,
                user_message_id=user_message_id,
                reply_message_id=reply_message_id,
                operator_id=operator_id or "",
                mode="basic",
            ):
                self.broadcast(
                    _chat_event({"type": "status", "value": "thinking"}, corr_id=corr_id),
                    operator_id=operator_id,
                )
                self.broadcast(
                    _chat_event(
                        {"type": "user", "text": text},
                        corr_id=corr_id,
                        message_id=user_message_id,
                    ),
                    operator_id=operator_id,
                )
                system = (CONFIG.llm.system_prompt or "You are Maya, a helpful assistant.").strip()
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ]
                parts: list[str] = []
                with _llm_lock:
                    stream = _voice_cue_filtered_stream(client.stream_messages(messages))
                    for chunk in stream:
                        parts.append(chunk)
                        self.broadcast(
                            _chat_event(
                                {"type": "ai", "text": chunk},
                                corr_id=corr_id,
                                message_id=reply_message_id,
                            ),
                            operator_id=operator_id,
                        )
                reply = "".join(parts).strip()
                completion_id = _llm_completion_id(client)
                self.broadcast(
                    _chat_event(
                        {"type": "status", "value": "idle"},
                        corr_id=corr_id,
                        message_id=reply_message_id,
                        completion_id=completion_id,
                    ),
                    operator_id=operator_id,
                )
                log.info(
                    "chat turn complete mode=basic corr_id=%s user_message_id=%s reply_message_id=%s completion_id=%s",
                    corr_id,
                    user_message_id,
                    reply_message_id,
                    completion_id or "",
                )
            return {"ok": True, "text": reply, "mode": "basic", "corr_id": corr_id}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            # #region agent log
            try:
                import json as _json, time as _time, traceback as _tb
                with open("/home/warby/Workspace-git/maya-unified/.cursor/debug-3692cd.log", "a") as _f:
                    _f.write(_json.dumps({"sessionId": "3692cd", "hypothesisId": "A_B_D", "location": "hub.py:_chat_text_basic", "message": "chat_text_basic exception", "data": {"exc_type": type(exc).__name__, "exc": msg, "traceback": _tb.format_exc()}, "timestamp": int(_time.time() * 1000)}) + "\n")
            except Exception:
                pass
            # #endregion
            self.broadcast({"type": "status", "value": "idle"}, operator_id=operator_id)
            self.broadcast({"type": "error", "text": msg}, operator_id=operator_id)
            return {"ok": False, "error": msg}

    def chat_text(self, text: str, operator_id: str | None = None) -> dict:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty message"}
        if not self.ready or self.agent is None:
            return self._chat_text_basic(text, operator_id=operator_id)
        from config import CONFIG

        history_override = None
        if operator_id:
            self.apply_operator_context(operator_id)
            from services.operator_voice import context as op_ctx

            history_override = op_ctx.get_history_messages(operator_id)
        if not is_webllm_provider():
            llm = self.llm_status(operator_id)
            if not llm.get("ok"):
                return {"ok": False, "error": llm.get("error") or "LLM unavailable"}
        try:
            corr_id = new_corr_id()
            user_message_id = new_message_id()
            reply_message_id = new_message_id()
            with span(
                "chat.corr",
                corr_id=corr_id,
                user_message_id=user_message_id,
                reply_message_id=reply_message_id,
                operator_id=operator_id or "",
                mode="enriched",
            ):
                self.broadcast(
                    _chat_event({"type": "status", "value": "thinking"}, corr_id=corr_id),
                    operator_id=operator_id,
                )
                self.broadcast(
                    _chat_event(
                        {"type": "user", "text": text},
                        corr_id=corr_id,
                        message_id=user_message_id,
                    ),
                    operator_id=operator_id,
                )
                messages = self.agent._build_messages(text, history_override=history_override)  # noqa: SLF001

                def _emit_chat(**ev: object) -> None:
                    payload = dict(ev)
                    if payload.get("type") == "ai":
                        payload = _chat_event(
                            payload,
                            corr_id=corr_id,
                            message_id=reply_message_id,
                        )
                    elif payload.get("type") in {"status", "delivery"}:
                        payload = _chat_event(payload, corr_id=corr_id)
                    self.broadcast(payload, operator_id=operator_id)

                plan = None
                if self.agent._should_orchestrate():  # noqa: SLF001
                    plan = self.agent._llm_orchestrate(text, text)  # noqa: SLF001

                reply = ""
                streamed = False
                with _inference_lock:
                    self.agent._avatar_mood_set_this_turn = False  # noqa: SLF001
                    if self.agent._tools_active():  # noqa: SLF001
                        anim_label = self.agent._maybe_play_avatar_animation(  # noqa: SLF001
                            text, plan=plan, raw_text=text,
                        )
                        if anim_label:
                            messages = self.agent._messages_with_animation_hint(  # noqa: SLF001
                                text, anim_label, history_override=history_override,
                            )
                            parts: list[str] = []
                            with _llm_lock:
                                stream = _voice_cue_filtered_stream(self.agent.llm.stream_messages(messages))  # noqa: SLF001
                                for chunk in stream:
                                    parts.append(chunk)
                                    self.broadcast(
                                        _chat_event(
                                            {"type": "ai", "text": chunk},
                                            corr_id=corr_id,
                                            message_id=reply_message_id,
                                        ),
                                        operator_id=operator_id,
                                    )
                            reply = "".join(parts).strip()
                            streamed = True
                        else:
                            result = self.agent.tool_loop.run(messages, emit=_emit_chat)  # noqa: SLF001
                            reply = (result.final_text or "").strip()
                    else:
                        parts = []
                        with _llm_lock:
                            stream = _voice_cue_filtered_stream(self.agent.llm.stream_messages(messages))
                            for chunk in stream:
                                parts.append(chunk)
                                self.broadcast(
                                    _chat_event(
                                        {"type": "ai", "text": chunk},
                                        corr_id=corr_id,
                                        message_id=reply_message_id,
                                    ),
                                    operator_id=operator_id,
                                )
                        reply = "".join(parts).strip()
                        streamed = True

                if reply and not streamed:
                    reply = _publish_ai_reply(self, reply, operator_id=operator_id)
                elif reply:
                    from agent import finalize_reply_text

                    reply, cue = finalize_reply_text(reply)
                    if cue:
                        self.broadcast(
                            _chat_event({"type": "delivery", "cue": cue}, corr_id=corr_id),
                            operator_id=operator_id,
                        )

                completion_id = _llm_completion_id(self.agent.llm)
                if reply:
                    self.agent._maybe_emit_avatar_mood(reply)  # noqa: SLF001
                    if operator_id:
                        from services.operator_voice import context as op_ctx

                        op_ctx.append_turn(
                            operator_id,
                            "user",
                            text,
                            message_id=user_message_id,
                            corr_id=corr_id,
                        )
                        op_ctx.append_turn(
                            operator_id,
                            "assistant",
                            reply,
                            message_id=reply_message_id,
                            corr_id=corr_id,
                            completion_id=completion_id,
                        )
                    else:
                        self.agent.history.append(
                            {
                                "role": "user",
                                "content": text,
                                "message_id": user_message_id,
                                "corr_id": corr_id,
                            }
                        )
                        self.agent.history.append(
                            {
                                "role": "assistant",
                                "content": reply,
                                "message_id": reply_message_id,
                                "corr_id": corr_id,
                                "completion_id": completion_id,
                            }
                        )
                self.broadcast(
                    _chat_event(
                        {"type": "status", "value": "idle"},
                        corr_id=corr_id,
                        message_id=reply_message_id,
                        completion_id=completion_id,
                    ),
                    operator_id=operator_id,
                )
                log.info(
                    "chat turn complete mode=enriched corr_id=%s user_message_id=%s reply_message_id=%s completion_id=%s",
                    corr_id,
                    user_message_id,
                    reply_message_id,
                    completion_id or "",
                )
            # #region agent log
            try:
                import json as _json, time as _time
                with open("/home/warby/Workspace-git/maya-unified/.cursor/debug-3692cd.log", "a") as _f:
                    _f.write(_json.dumps({"sessionId": "3692cd", "runId": "post-fix", "hypothesisId": "A", "location": "hub.py:chat_text/enriched", "message": "chat_text enriched success (current corr_id code ran)", "data": {"corr_id": corr_id, "reply_len": len(reply)}, "timestamp": int(_time.time() * 1000)}) + "\n")
            except Exception:
                pass
            # #endregion
            return {"ok": True, "text": reply, "corr_id": corr_id}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            # #region agent log
            try:
                import json as _json, time as _time, traceback as _tb
                with open("/home/warby/Workspace-git/maya-unified/.cursor/debug-3692cd.log", "a") as _f:
                    _f.write(_json.dumps({"sessionId": "3692cd", "hypothesisId": "A_B_C", "location": "hub.py:chat_text/enriched", "message": "chat_text enriched exception", "data": {"exc_type": type(exc).__name__, "exc": msg, "traceback": _tb.format_exc()}, "timestamp": int(_time.time() * 1000)}) + "\n")
            except Exception:
                pass
            # #endregion
            self.broadcast({"type": "status", "value": "idle"}, operator_id=operator_id)
            self.broadcast({"type": "error", "text": msg}, operator_id=operator_id)
            return {"ok": False, "error": msg}

    def chat_in_room(
        self,
        room_id: str,
        text: str,
        *,
        member_name: str,
        history: list[dict],
        snapshot: dict[str, Any],
    ) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": self.last_error or "agent not ready"}
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty message"}
        self.apply_room_context(room_id, snapshot)
        user_line = f"{member_name}: {text}"
        try:
            corr_id = new_corr_id()
            user_message_id = new_message_id()
            reply_message_id = new_message_id()
            with span(
                "chat.corr",
                corr_id=corr_id,
                user_message_id=user_message_id,
                reply_message_id=reply_message_id,
                room_id=room_id,
                mode="room",
            ):
                self.broadcast(
                    _chat_event({"type": "status", "value": "thinking"}, corr_id=corr_id),
                    room_id=room_id,
                )
                self.broadcast(
                    _chat_event(
                        {"type": "user", "text": user_line},
                        corr_id=corr_id,
                        message_id=user_message_id,
                    ),
                    room_id=room_id,
                )
                messages = self.agent._build_messages(user_line, history_override=history)  # noqa: SLF001
                parts: list[str] = []
                with _llm_lock:
                    stream = _voice_cue_filtered_stream(self.agent.llm.stream_messages(messages))
                    for chunk in stream:
                        parts.append(chunk)
                        self.broadcast(
                            _chat_event(
                                {"type": "ai", "text": chunk},
                                corr_id=corr_id,
                                message_id=reply_message_id,
                            ),
                            room_id=room_id,
                        )
                reply = "".join(parts).strip()
                completion_id = _llm_completion_id(self.agent.llm)
                self.broadcast(
                    _chat_event(
                        {"type": "status", "value": "idle"},
                        corr_id=corr_id,
                        message_id=reply_message_id,
                        completion_id=completion_id,
                    ),
                    room_id=room_id,
                )
                log.info(
                    "chat turn complete mode=room corr_id=%s user_message_id=%s reply_message_id=%s completion_id=%s room_id=%s",
                    corr_id,
                    user_message_id,
                    reply_message_id,
                    completion_id or "",
                    room_id,
                )
            return {"ok": True, "text": reply, "corr_id": corr_id}
        except Exception as exc:  # noqa: BLE001
            self.broadcast({"type": "status", "value": "idle"}, room_id=room_id)
            return {"ok": False, "error": str(exc)}

    def speak_text(self, text: str, *, instruct: str | None = None, operator_id: str | None = None) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": self.last_error or "agent not ready"}
        if operator_id:
            self.apply_operator_context(operator_id)
        from config import CONFIG

        self.agent.playback.set_output_sink(CONFIG.audio.output_sink)
        self.agent.playback.set_output_volume(CONFIG.audio.output_volume)
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty text"}
        from agent import finalize_reply_text

        text, cue = finalize_reply_text(text)
        if not text:
            return {"ok": False, "error": "empty text"}
        instruct = (instruct or "").strip() or cue or None

        def _run() -> None:
            try:
                with _tts_lock:
                    self.agent.speak_preview(text, instruct=instruct)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.broadcast({"type": "status", "value": "idle"}, operator_id=operator_id)
                self.broadcast({"type": "tts_error", "text": msg}, operator_id=operator_id)

        threading.Thread(target=_run, daemon=True, name="tts-preview").start()
        return {"ok": True}

    def render_speech(
        self, text: str, *, instruct: str | None = None, operator_id: str | None = None
    ) -> tuple[bytes, int, dict[str, float]]:
        import time

        if not self.ready or self.agent is None:
            raise RuntimeError(self.last_error or "agent not ready")
        voice = self.agent.voice
        if voice is None or not getattr(voice, "available", True):
            raise RuntimeError(getattr(voice, "degrade_reason", "TTS unavailable"))
        if operator_id:
            self.apply_operator_context(operator_id)
        text = (text or "").strip()
        if not text:
            raise ValueError("empty text")
        from agent import finalize_reply_text

        text, cue = finalize_reply_text(text)
        if not text:
            raise ValueError("empty text")
        instruct = (instruct or "").strip() or cue or None
        lock_wait_start = time.perf_counter()
        with _tts_lock:
            lock_wait_ms = (time.perf_counter() - lock_wait_start) * 1000.0
            wav_bytes, sr, timing = self.agent.render_speech(text, instruct=instruct)
        timing = {**timing, "lock_wait_ms": lock_wait_ms}
        try:
            from observability import record_tts

            record_tts(timing)
        except ImportError:
            pass
        return wav_bytes, sr, timing

    def iter_speech(
        self, text: str, *, instruct: str | None = None, operator_id: str | None = None
    ):
        """Stream PCM chunks under the TTS lock (generator must be consumed promptly)."""
        import time

        if not self.ready or self.agent is None:
            raise RuntimeError(self.last_error or "agent not ready")
        voice = self.agent.voice
        if voice is None or not getattr(voice, "available", True):
            raise RuntimeError(getattr(voice, "degrade_reason", "TTS unavailable"))
        if operator_id:
            self.apply_operator_context(operator_id)
        text = (text or "").strip()
        if not text:
            raise ValueError("empty text")
        from agent import finalize_reply_text

        text, cue = finalize_reply_text(text)
        if not text:
            raise ValueError("empty text")
        instruct = (instruct or "").strip() or cue or None
        lock_wait_start = time.perf_counter()
        with _tts_lock:
            lock_wait_ms = (time.perf_counter() - lock_wait_start) * 1000.0
            first = True
            for pcm, sr, is_first, engine_timing in self.agent.iter_speech(text, instruct=instruct):
                if first:
                    yield pcm, sr, is_first, {**engine_timing, "lock_wait_ms": lock_wait_ms}
                    first = False
                else:
                    yield pcm, sr, is_first, engine_timing

    def start(self, operator_id: str | None = None) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        if not operator_id:
            return self._start_session_guarded()
        lease = VoiceLease(kind="operator", context_id=str(operator_id), speaker_id=str(operator_id))
        denied = self._acquire_lease(lease)
        if not denied.get("ok"):
            return {
                "ok": False,
                "error": denied.get("error", "voice_in_use"),
                "owner": denied.get("owner"),
            }
        self.apply_operator_context(operator_id)
        result = self._start_session_guarded(operator_id=operator_id)
        if not result.get("ok"):
            self._release_lease(
                kind="operator", context_id=str(operator_id), speaker_id=str(operator_id)
            )
        return result

    def _start_session_guarded(self, operator_id: str | None = None) -> dict:
        """Start the mic session, degrading gracefully if local audio is unavailable."""
        from player import AudioUnavailable

        try:
            self.agent.start_session()
            return {"ok": True}
        except AudioUnavailable as exc:
            msg = str(exc)
            self.broadcast(
                {"type": "status", "value": "idle"}, operator_id=operator_id
            )
            self.broadcast({"type": "audio_degraded", "text": msg}, operator_id=operator_id)
            return {"ok": False, "error": msg}

    def stop(self, operator_id: str | None = None) -> dict:
        if operator_id:
            self._release_lease(kind="operator", context_id=str(operator_id), speaker_id=str(operator_id))
        if self.agent is not None:
            self.agent.stop_session()
        return {"ok": True}

    def start_room_voice(self, room_id: str, member_id: str, member_name: str, snapshot: dict) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        lease = VoiceLease(
            kind="room",
            context_id=str(room_id),
            speaker_id=str(member_id),
            speaker_name=member_name,
        )
        denied = self._acquire_lease(lease)
        if not denied.get("ok"):
            return {
                "ok": False,
                "error": denied.get("error", "voice_in_use"),
                "owner": denied.get("owner"),
            }
        self.apply_room_context(room_id, snapshot)
        self.agent.start_session()
        self.broadcast({"type": "queue_granted", "member_id": member_id}, room_id=room_id)
        return {"ok": True}

    def stop_room_voice(self, room_id: str, member_id: str) -> dict:
        self._release_lease(kind="room", context_id=str(room_id), speaker_id=str(member_id))
        if self.agent is not None:
            self.agent.stop_session()
        self.broadcast({"type": "queue_released", "member_id": member_id}, room_id=room_id)
        return {"ok": True}

    def load_settings_for_operator(self, operator_id: str) -> dict:
        from services.operator_voice import context as op_ctx

        return op_ctx.load_settings(operator_id)

    def list_personalities_for_operator(self, operator_id: str) -> dict:
        self.apply_operator_context(operator_id)
        return self.list_personalities()

    def activate_personality_for_operator(self, operator_id: str, personality_id: str) -> dict:
        self.apply_operator_context(operator_id)
        result = self.activate_personality(personality_id)
        from services.operator_voice import context as op_ctx

        pers = op_ctx.load_personalities(operator_id)
        op_ctx.save_personalities(operator_id, active=personality_id, personalities=pers.get("personalities"))
        op_ctx.save_settings(operator_id, {"personality": {"active_id": personality_id}})
        return result


hub = VoiceHub()

from services.llm import webllm_broker  # noqa: E402

webllm_broker.set_broadcast(hub.broadcast)
