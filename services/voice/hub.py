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


def _publish_ai_reply(
    hub: "VoiceHub",
    raw: str,
    *,
    operator_id: str | None = None,
    room_id: str | None = None,
    corr_id: str | None = None,
    message_id: str | None = None,
    motion_turn: bool = False,
    user_text: str = "",
    anim_label: str = "",
    agent: object | None = None,
) -> tuple[str, str | None]:
    """Strip VOICE: cues and broadcast one clean assistant turn."""
    from agent import finalize_reply_text

    reply, cue = finalize_reply_text(raw)
    if not reply and motion_turn and agent is not None:
        reply = agent._fallback_avatar_reply(user_text, anim_label)  # noqa: SLF001
        cue = None
    if reply:
        base = {"type": "ai", "text": reply, "final": True}
        payload = _chat_event(base, corr_id=corr_id, message_id=message_id) if corr_id else base
        hub.broadcast(payload, operator_id=operator_id, room_id=room_id)
    if cue:
        delivery = {"type": "delivery", "cue": cue}
        payload = _chat_event(delivery, corr_id=corr_id) if corr_id else delivery
        hub.broadcast(payload, operator_id=operator_id, room_id=room_id)
    return reply, cue


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


def _saved_tts_model_id(settings: dict) -> str:
    delivery = settings.get("delivery") if isinstance(settings.get("delivery"), dict) else {}
    voice = settings.get("voice") if isinstance(settings.get("voice"), dict) else {}
    mode = str(delivery.get("tts_mode") or "clone").lower()
    if mode == "clone":
        return str(voice.get("clone_model") or "")
    return str(voice.get("custom_model") or "")


def _loaded_tts_model_id(agent) -> str:
    voice = getattr(agent, "voice", None)
    return str(getattr(voice, "model_id", "") or "")


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
    _last_user_text: str = ""
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
        if operator_id and not room_id:
            from services.dashboard.player import replay_player_to_subscriber

            replay_player_to_subscriber(q, operator_id=operator_id)
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
        global_types = frozenset({"ready", "status", "error", "audio", "audio_begin", "audio_stop", "lip"})
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
        from services.operator_voice.context import reconcile_operator_personalities
        from services.operator_voice.memory_migration import (
            copy_global_memory_to_operator,
            seed_operator_skills_from_examples,
        )
        from services.operator_voice.paths import seed_operator_dirs

        oid = str(operator_id)
        operator_changed = oid != (self._active_operator_id or "")
        seed_operator_dirs(operator_id)
        copy_global_memory_to_operator(oid)
        seed_operator_skills_from_examples(oid)
        data_dir = op_data_dir(operator_id)
        os.environ["VA_DATA_DIR"] = str(data_dir)
        settings = load_effective_settings(operator_id)
        apply_to_config(settings, operator_id=operator_id)
        if self.ready and self.agent is not None:
            from config import CONFIG

            self.agent.playback.set_output_sink(CONFIG.audio.output_sink)
            swap_agent_llm(self.agent, operator_id=oid)
            if self.agent.memory is not None:
                self.agent.rebind_memory(str(data_dir.resolve()))
        self._active_operator_id = oid
        self._active_room_id = None
        if self.ready and self.agent is not None:
            self.agent._vision_operator_id = oid  # noqa: SLF001
            self.agent._vision_reasoning = dict(settings.get("reasoning") or {})  # noqa: SLF001
        self._activate_effective_personality(operator_id, settings)
        if operator_changed and self.ready and self.agent is not None:
            want = _saved_tts_model_id(settings)
            loaded = _loaded_tts_model_id(self.agent)
            if want and loaded and want != loaded:
                self._reload_tts_engine(settings, operator_id=oid)

    def _activate_effective_personality(
        self,
        operator_id: str | None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        if not self.ready or self.agent is None:
            return
        from services.operator_voice.context import (
            reconcile_operator_personalities,
            resolve_active_personality_id,
        )
        from services.operator_voice.paths import load_legacy_global_personalities

        active = ""
        if operator_id:
            pers_data = reconcile_operator_personalities(operator_id)
            active = str(pers_data.get("active") or "")
        else:
            effective = settings if settings is not None else load_effective_settings(None)
            legacy = load_legacy_global_personalities()
            personalities = legacy.get("personalities") if isinstance(legacy.get("personalities"), dict) else {}
            settings_active = str(effective.get("personality", {}).get("active_id") or "")
            active = resolve_active_personality_id(
                personalities,
                file_active=str(legacy.get("active") or ""),
                settings_active_id=settings_active,
            )
        if not active:
            return
        try:
            self.agent.activate_personality(active)
        except Exception:  # noqa: BLE001
            log.exception("failed to activate personality %s", active)

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
        if agent is not None:
            try:
                from tts import release_tts

                release_tts(getattr(agent, "voice", None))
            except Exception:  # noqa: BLE001
                pass
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
            oid = self._active_operator_id
            if oid:
                self.apply_operator_context(oid)
                settings = load_effective_settings(oid)
            else:
                settings = load_effective_settings(None)
                apply_to_config(settings, operator_id=oid)
                os.environ["VA_DATA_DIR"] = str(DATA_DIR)
            from services.discord.unified_bot import apply_discord_env

            apply_discord_env(settings)

            from agent import VoiceAgent

            self.broadcast({"type": "status", "value": "loading"})
            agent = VoiceAgent(mode="vad", on_event=self._agent_event)
            swap_agent_llm(agent, operator_id=oid)
            self.agent = agent
            from services.discord.patch_agent import patch_voice_agent

            patch_voice_agent(agent)
            from config import CONFIG

            agent.playback.set_output_sink(CONFIG.audio.output_sink)
            self.current_voice = os.path.basename(CONFIG.tts.ref_audio)
            self.ready = True
            self._apply_voice_settings_hot_swap(settings)
            if oid:
                self._activate_effective_personality(oid, settings)
            else:
                self._activate_effective_personality(None, settings)
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
        if event.get("type") in ("audio", "audio_begin", "audio_stop", "lip"):
            op = self._active_operator_id
            self.broadcast(event, operator_id=op, room_id=None)
            return
        op = self._active_operator_id
        room = self._active_room_id
        self.broadcast(event, operator_id=op, room_id=room)

    def apply_settings_patch(self, patch: dict, operator_id: str | None = None) -> dict:
        from services.llm.api_keys import is_placeholder_api_key
        from services.operator_voice import context as op_ctx

        reasoning_patch = patch.get("reasoning") if isinstance(patch, dict) else {}
        api_key_supplied = (
            isinstance(reasoning_patch, dict)
            and "api_key" in reasoning_patch
            and not is_placeholder_api_key(str(reasoning_patch.get("api_key") or ""))
        )

        if operator_id:
            self.apply_operator_context(operator_id)
            previous = op_ctx.load_settings(operator_id)
            merged = op_ctx.save_settings(operator_id, patch if isinstance(patch, dict) else {})
        else:
            previous = load_global_settings()
            merged = save_global_settings(patch if isinstance(patch, dict) else {}, operator_id=None)
        if merged == previous and not api_key_supplied:
            return merged

        if operator_id:
            _mirror_operator_runtime_globals(previous, merged)

        apply_to_config(merged, operator_id=operator_id)
        from services.discord.unified_bot import apply_discord_env

        apply_discord_env(merged)
        if _section_changed(previous, merged, "reasoning"):
            from services.llm.health import invalidate_llm_health_cache

            invalidate_llm_health_cache()
        if _section_changed(previous, merged, "discord") or _section_changed(previous, merged, "imagine"):
            from services.discovery.registry import refresh_comfyui
            from services.imagine.health import invalidate_comfyui_health_cache

            invalidate_comfyui_health_cache()
            refresh_comfyui(merged)
        needs_reload = any(_section_changed(previous, merged, s) for s in _RELOAD_SECTIONS)
        tts_reload = _tts_engine_changed(previous, merged)
        if tts_reload and not needs_reload and self.ready and self.agent is not None:
            self._reload_tts_engine(merged, operator_id=operator_id)
            self.broadcast(_settings_broadcast_payload(merged), operator_id=operator_id)
            return merged
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
                swap_agent_llm(self.agent, operator_id=operator_id)
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
        from services.discovery.policy import imagine_capability_ready
        from services.discovery.registry import snapshot as services_snapshot
        from services.imagine.health import get_cached_comfyui_health
        from services.imagine.settings import get_imagine_settings
        from services.llm.health import build_agent_capabilities, get_cached_llm_health

        settings = load_effective_settings(operator_id)
        imagine_enabled = bool(get_imagine_settings(settings).get("enabled"))
        if imagine_enabled:
            imagine_health = get_cached_comfyui_health(
                settings, run_probe=False, operator_id=operator_id
            )
            imagine_ready = imagine_capability_ready(imagine_health, settings=settings)
        else:
            imagine_health = None
            imagine_ready = False
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
            caps = build_agent_capabilities(
                self.ready, health, reasoning, imagine_ready=imagine_ready
            )
            # WebLLM chat is routed through the voice agent bridge, not server-side LLM.
            caps["text_chat"] = self.ready and browser_ready
            caps["text_chat_enriched"] = caps["text_chat"]
            caps["vision"] = False
            return {
                "health": health,
                "capabilities": caps,
                "llm_ready": caps["text_chat"],
                "imagine_enabled": imagine_enabled,
                "imagine_health": imagine_health,
                "services": services_snapshot(),
            }
        health = get_cached_llm_health(
            reasoning if isinstance(reasoning, dict) else {},
            operator_id=operator_id,
        )
        caps = build_agent_capabilities(
            self.ready,
            health,
            reasoning if isinstance(reasoning, dict) else {},
            imagine_ready=imagine_ready,
        )
        return {
            "health": health,
            "capabilities": caps,
            "llm_ready": caps["text_chat"],
            "imagine_enabled": imagine_enabled,
            "imagine_health": imagine_health,
            "services": services_snapshot(),
        }

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

    def _reload_tts_engine(self, settings: dict, *, operator_id: str | None = None) -> None:
        """Unload the in-memory TTS stack and load weights from saved settings."""
        import logging

        log = logging.getLogger("maya-unified.voice")
        if operator_id:
            self.apply_operator_context(operator_id)
        else:
            apply_to_config(settings, operator_id=None)
        if not self.ready or self.agent is None:
            self.request_agent_reload()
            return
        delivery = settings.get("delivery") or {}
        voice = settings.get("voice") or {}
        target_mode = str(delivery.get("tts_mode") or "clone").lower()
        target_model = (
            str(voice.get("clone_model") or "")
            if target_mode == "clone"
            else str(voice.get("custom_model") or "")
        )
        self.broadcast({"type": "status", "value": "loading"})
        self.broadcast(
            {
                "type": "tts_reload",
                "phase": "start",
                "mode": target_mode,
                "model_id": target_model,
            }
        )
        try:
            result = self.agent.reload_tts()
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "TTS reload failed")
            self._apply_voice_settings_hot_swap(settings)
            loaded = str(result.get("model_id") or "")
            self.broadcast(
                {
                    "type": "tts_reload",
                    "phase": "done",
                    "model_id": loaded,
                    "previous_model_id": result.get("previous_model_id", ""),
                }
            )
            log.info("TTS engine reloaded -> %s", loaded)
        except Exception as exc:  # noqa: BLE001
            log.exception("TTS reload failed, falling back to full agent reload")
            self.broadcast({"type": "error", "text": f"TTS reload failed: {exc}"})
            self.request_agent_reload()
            return
        finally:
            if self.ready:
                self.broadcast({"type": "status", "value": "idle"})

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
        apply_to_config({"reasoning": reasoning}, operator_id=operator_id)
        health = get_cached_llm_health(reasoning, run_probe=True, operator_id=operator_id)
        if not llm_ready_from_health(health):
            return {"ok": False, "error": health.get("detail") or "LLM unavailable"}
        try:
            corr_id = new_corr_id()
            user_message_id = new_message_id()
            reply_message_id = new_message_id()
            client = create_llm_client(operator_id=operator_id)
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
                from vision import resolve_vision_user_content

                user_content = resolve_vision_user_content(
                    text,
                    text,
                    operator_id,
                    reasoning,
                    model=CONFIG.llm.model,
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ]
                parts: list[str] = []
                with _llm_lock:
                    stream = _voice_cue_filtered_stream(client.stream_messages(messages))
                    for chunk in stream:
                        parts.append(chunk)
                reply = "".join(parts).strip()
                completion_id = _llm_completion_id(client)
                if reply:
                    reply, _ = _publish_ai_reply(
                        self,
                        reply,
                        operator_id=operator_id,
                        corr_id=corr_id,
                        message_id=reply_message_id,
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
                    "chat turn complete mode=basic corr_id=%s user_message_id=%s reply_message_id=%s completion_id=%s",
                    corr_id,
                    user_message_id,
                    reply_message_id,
                    completion_id or "",
                )
            return {"ok": True, "text": reply, "mode": "basic", "corr_id": corr_id}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            self.broadcast({"type": "status", "value": "idle"}, operator_id=operator_id)
            self.broadcast({"type": "error", "text": msg}, operator_id=operator_id)
            return {"ok": False, "error": msg}

    def _schedule_chat_tts(
        self,
        text: str,
        *,
        instruct: str | None,
        operator_id: str | None,
        corr_id: str,
        idle_event: dict,
    ) -> bool:
        """Speak a typed-chat reply with TTS + lip-sync events (async)."""
        if not self.ready or self.agent is None:
            return False
        voice = self.agent.voice
        if voice is None or not getattr(voice, "available", True):
            return False
        body = (text or "").strip()
        if not body:
            return False

        def _run() -> None:
            try:
                from config import CONFIG

                with _tts_lock:
                    self.agent.playback.set_output_sink(CONFIG.audio.output_sink)
                    self.agent.playback.set_output_volume(CONFIG.audio.output_volume)
                    self.agent.speak_chat_reply(
                        body,
                        instruct=instruct,
                        corr_id=corr_id,
                        emit_final_status=False,
                    )
                self.broadcast(idle_event, operator_id=operator_id)
            except Exception as exc:  # noqa: BLE001
                log.exception("chat TTS failed")
                self.broadcast(
                    _chat_event({"type": "tts_error", "text": str(exc)}, corr_id=corr_id),
                    operator_id=operator_id,
                )
                self.broadcast(idle_event, operator_id=operator_id)

        threading.Thread(target=_run, daemon=True, name="chat-tts").start()
        return True

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
            reply = ""
            streamed = False
            imagine_artifact_emitted = False
            self._last_user_text = text
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

                plan = None
                if self.agent._should_orchestrate():  # noqa: SLF001
                    plan = self.agent._llm_orchestrate(text, text)  # noqa: SLF001

                from services.imagine.tool_context import set_imagine_tool_context

                set_imagine_tool_context(operator_id=operator_id, corr_id=corr_id)
                try:
                    from services.imagine.director_context import set_image_director_context

                    set_image_director_context(operator_id=operator_id, corr_id=corr_id)
                except ImportError:
                    pass

                from services.imagine.chat_fallback import trace_has_imagine_success
                from services.imagine.intent import (
                    looks_like_director_refinement,
                    looks_like_imagine_request,
                    looks_like_music_playback_request,
                )
                from services.imagine.settings import get_imagine_settings

                effective_settings = load_effective_settings(operator_id)
                imagine_settings = get_imagine_settings(effective_settings)
                imagine_nl = (
                    looks_like_imagine_request(text)
                    and bool(imagine_settings.get("enabled"))
                )

                tool_trace: list[dict] = []

                def _emit_chat(**ev: object) -> None:
                    nonlocal streamed, imagine_artifact_emitted
                    payload = dict(ev)
                    ev_type = str(payload.get("type") or "")
                    if payload.get("type") == "ai":
                        if payload.get("text") or payload.get("artifacts"):
                            streamed = True
                        if payload.get("artifacts"):
                            imagine_artifact_emitted = True
                        payload = _chat_event(
                            payload,
                            corr_id=corr_id,
                            message_id=reply_message_id,
                        )
                    elif ev_type.startswith("image.director."):
                        payload = _chat_event(
                            payload,
                            corr_id=corr_id,
                            message_id=reply_message_id,
                        )
                        if ev_type != "image.director.versions":
                            streamed = True
                    elif payload.get("type") in {"status", "delivery"}:
                        payload = _chat_event(payload, corr_id=corr_id)
                    elif payload.get("type") in {"tool_start", "tool_end", "tool_trace"}:
                        payload = _chat_event(payload, corr_id=corr_id)
                    elif payload.get("type") == "system" and payload.get("text"):
                        payload = _chat_event(payload, corr_id=corr_id)
                    self.broadcast(payload, operator_id=operator_id)

                reply = ""
                anim_label = ""
                motion_turn = False
                direct = None
                if self.agent._tools_active():  # noqa: SLF001
                    if plan and plan.intent not in ("chat", "unknown", "none"):  # noqa: SLF001
                        direct = self.agent._execute_orchestrator_plan(plan, text, text)  # noqa: SLF001
                    if direct is None:
                        direct = self.agent._try_pending_action_direct(text)  # noqa: SLF001
                    if direct is None and not self.agent._maybe_motion_request(  # noqa: SLF001
                        text, plan=plan, raw_text=text,
                    ):
                        try:
                            from services.game.enabled import GAME_MODE_ENABLED
                        except ImportError:
                            GAME_MODE_ENABLED = False
                        if GAME_MODE_ENABLED:
                            direct = self.agent._try_game_direct(text)  # noqa: SLF001
                    if direct is None and not self.agent._maybe_motion_request(  # noqa: SLF001
                        text, plan=plan, raw_text=text,
                    ):
                        if self.agent._is_discord_context_turn(text):  # noqa: SLF001
                            direct = self.agent._try_discord_direct(text)  # noqa: SLF001
                        else:
                            direct = self.agent._try_bandcamp_direct(text)  # noqa: SLF001
                            if direct is None:
                                direct = self.agent._try_dashboard_music_direct(text)  # noqa: SLF001
                            if direct is None:
                                direct = self.agent._try_dashboard_queue_direct(text)  # noqa: SLF001
                            if direct is None:
                                direct = self.agent._try_discord_direct(text)  # noqa: SLF001
                with _inference_lock:
                    self.agent._avatar_mood_set_this_turn = False  # noqa: SLF001
                    if direct:
                        reply = direct
                    elif self.agent._tools_active():  # noqa: SLF001
                        anim_label = ""
                        if not imagine_nl:
                            anim_label = self.agent._maybe_play_avatar_animation(  # noqa: SLF001
                                text, plan=plan, raw_text=text,
                            ) or ""
                        motion_turn = bool(
                            anim_label
                            or self.agent._maybe_motion_request(  # noqa: SLF001
                                text, plan=plan, raw_text=text,
                            )
                        )
                        if motion_turn:
                            messages = (
                                self.agent._messages_with_animation_hint(  # noqa: SLF001
                                    text, anim_label or "gesture",
                                    history_override=history_override,
                                )
                                if anim_label
                                else self.agent._build_messages(  # noqa: SLF001
                                    text, history_override=history_override,
                                )
                            )
                            parts: list[str] = []
                            with _llm_lock:
                                stream = _voice_cue_filtered_stream(self.agent.llm.stream_messages(messages))  # noqa: SLF001
                                for chunk in stream:
                                    parts.append(chunk)
                            reply = "".join(parts).strip()
                        else:
                            tool_rounds = None
                            if imagine_nl or looks_like_director_refinement(text):
                                try:
                                    from tools.image_director import image_director_max_rounds

                                    tool_rounds = image_director_max_rounds()
                                except ImportError:
                                    pass
                            result = self.agent.tool_loop.run(  # noqa: SLF001
                                messages,
                                emit=_emit_chat,
                                max_rounds=tool_rounds,
                            )
                            reply = (result.final_text or "").strip()
                            tool_trace = list(result.trace or [])
                            if tool_trace:
                                self.broadcast(
                                    _chat_event(
                                        {"type": "tool_trace", "trace": tool_trace},
                                        corr_id=corr_id,
                                    ),
                                    operator_id=operator_id,
                                )
                            from services.dashboard.music_intent import (
                                looks_like_dashboard_queue_request,
                            )

                            def _trace_has_tool(trace: list[dict], name: str) -> bool:
                                return any(entry.get("tool") == name for entry in trace)

                            if (
                                looks_like_dashboard_queue_request(text)
                                and not _trace_has_tool(tool_trace, "dashboard_queue_music")
                            ):
                                guarded = self.agent._try_dashboard_queue_direct(text)  # noqa: SLF001
                                if guarded:
                                    reply = guarded
                            try:
                                from services.game.enabled import GAME_MODE_ENABLED
                            except ImportError:
                                GAME_MODE_ENABLED = False
                            if GAME_MODE_ENABLED:
                                try:
                                    from services.game.intent import is_game_play_request
                                except ImportError:
                                    is_game_play_request = lambda _t: False  # noqa: E731
                                if (
                                    is_game_play_request(text)
                                    and not _trace_has_tool(tool_trace, "game_play_until_goal")
                                ):
                                    guarded = self.agent._try_game_direct(text)  # noqa: SLF001
                                    if guarded:
                                        reply = guarded
                            if (
                                imagine_nl
                                and not trace_has_imagine_success(tool_trace)
                                and not looks_like_music_playback_request(text)
                            ):
                                from services.imagine.chat_fallback import run_imagine_nl_fallback

                                fallback_reply, fallback_streamed = run_imagine_nl_fallback(
                                    user_text=text,
                                    operator_id=operator_id,
                                    corr_id=corr_id,
                                    messages=messages,
                                    llm=self.agent.llm,  # noqa: SLF001
                                    emit=_emit_chat,
                                    settings=effective_settings,
                                )
                                reply = fallback_reply
                                streamed = streamed or fallback_streamed
                    else:
                        parts = []
                        with _llm_lock:
                            stream = _voice_cue_filtered_stream(self.agent.llm.stream_messages(messages))
                            for chunk in stream:
                                parts.append(chunk)
                        reply = "".join(parts).strip()

                delivery_cue = None
                if reply and not streamed:
                    leaked = self.agent._apply_pseudo_tool_calls_from_text(reply)  # noqa: SLF001
                    if leaked:
                        reply = leaked
                    reply, delivery_cue = _publish_ai_reply(
                        self,
                        reply,
                        operator_id=operator_id,
                        corr_id=corr_id,
                        message_id=reply_message_id,
                        motion_turn=motion_turn,
                        user_text=text,
                        anim_label=anim_label,
                        agent=self.agent,
                    )
                elif reply:
                    from agent import finalize_reply_text

                    _, delivery_cue = finalize_reply_text(reply)
                    if delivery_cue:
                        self.broadcast(
                            _chat_event({"type": "delivery", "cue": delivery_cue}, corr_id=corr_id),
                            operator_id=operator_id,
                        )
                    if streamed:
                        self.broadcast(
                            _chat_event(
                                {"type": "ai", "text": reply, "final": True},
                                corr_id=corr_id,
                                message_id=reply_message_id,
                            ),
                            operator_id=operator_id,
                        )
                elif motion_turn:
                    reply, delivery_cue = _publish_ai_reply(
                        self,
                        "",
                        operator_id=operator_id,
                        corr_id=corr_id,
                        message_id=reply_message_id,
                        motion_turn=True,
                        user_text=text,
                        anim_label=anim_label,
                        agent=self.agent,
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
                idle_event = _chat_event(
                    {"type": "status", "value": "idle"},
                    corr_id=corr_id,
                    message_id=reply_message_id,
                    completion_id=completion_id,
                )
                if not reply or not self._schedule_chat_tts(
                    reply,
                    instruct=delivery_cue,
                    operator_id=operator_id,
                    corr_id=corr_id,
                    idle_event=idle_event,
                ):
                    self.broadcast(idle_event, operator_id=operator_id)
                if reply and self.agent.memory is not None:
                    try:
                        self.agent.memory.log_turn(text, reply)
                        self.agent.memory.schedule_review(text, reply)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("chat memory review failed: %s", exc)
                log.info(
                    "chat turn complete mode=enriched corr_id=%s user_message_id=%s reply_message_id=%s completion_id=%s",
                    corr_id,
                    user_message_id,
                    reply_message_id,
                    completion_id or "",
                )
            return {"ok": True, "text": reply, "corr_id": corr_id}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            self.broadcast({"type": "status", "value": "idle"}, operator_id=operator_id)
            if imagine_artifact_emitted:
                log.warning("chat turn failed after imagine artifact corr_id=%s: %s", corr_id, msg)
                return {"ok": True, "text": reply or "", "corr_id": corr_id}
            self.broadcast({"type": "error", "text": msg}, operator_id=operator_id)
            return {"ok": False, "error": msg}

    async def stream_imagine_remark(
        self,
        *,
        operator_id: str | None,
        corr_id: str,
        reply_message_id: str,
        prompt: str,
        artifact: dict,
        artifacts: list | None = None,
    ) -> str:
        import asyncio

        from services.imagine.remark import (
            build_remark_messages,
            remark_enabled,
            remark_vision_model,
            stream_remark_text,
        )
        from services.settings.store import load_effective_settings

        settings = await asyncio.to_thread(load_effective_settings, operator_id)
        if not remark_enabled(settings):
            return ""
        if not self.ready or self.agent is None:
            return ""

        system = self.agent.llm.base_system_prompt()
        messages, vision_used = build_remark_messages(
            prompt=prompt,
            artifact=artifact,
            system_prompt=system,
            settings=settings,
        )
        artifact_list = artifacts if artifacts else [artifact]

        self.broadcast(
            _chat_event({"type": "status", "value": "thinking"}, corr_id=corr_id),
            operator_id=operator_id,
        )

        def _emit(**ev: object) -> None:
            kind = ev.get("type") if isinstance(ev, dict) else None
            if kind == "ai":
                chunk = str(ev.get("text") or "")
                if not chunk:
                    return
                payload = {
                    "type": "ai",
                    "text": chunk,
                    "mode": "cmd",
                    "cmd_phase": "remark",
                    "artifacts": artifact_list,
                }
                self.broadcast(
                    _chat_event(payload, corr_id=corr_id, message_id=reply_message_id),
                    operator_id=operator_id,
                )
            elif kind == "delivery" and ev.get("cue"):
                self.broadcast(
                    _chat_event({"type": "delivery", "cue": ev["cue"]}, corr_id=corr_id),
                    operator_id=operator_id,
                )

        with span(
            "imagine.remark",
            vision_enabled=vision_used,
            image_job_id=str(artifact.get("job_id") or ""),
            chat_corr_id=corr_id,
        ):
            with _inference_lock:
                with _llm_lock:
                    remark = await asyncio.to_thread(
                        stream_remark_text,
                        self.agent.llm,
                        messages,
                        emit=_emit,
                        vision_model=remark_vision_model(settings) if vision_used else "",
                    )

        if remark and operator_id:
            from services.operator_voice import context as op_ctx

            op_ctx.append_turn(
                operator_id,
                "assistant",
                remark,
                message_id=reply_message_id,
                corr_id=corr_id,
            )

        self.broadcast(
            _chat_event(
                {"type": "status", "value": "idle"},
                corr_id=corr_id,
                message_id=reply_message_id,
            ),
            operator_id=operator_id,
        )
        return remark

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
                reply = "".join(parts).strip()
                if reply:
                    reply, _ = _publish_ai_reply(
                        self,
                        reply,
                        room_id=room_id,
                        corr_id=corr_id,
                        message_id=reply_message_id,
                    )
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
        from services.operator_voice import context as op_ctx

        op_ctx.reconcile_operator_personalities(operator_id)
        self.apply_operator_context(operator_id)
        return self.list_personalities()

    def _finish_operator_personality_mutation(self, operator_id: str, result: dict) -> dict:
        if not result.get("ok"):
            return result
        from services.operator_voice import context as op_ctx

        op_ctx.persist_operator_personalities_from_file(operator_id)
        active = str(result.get("active") or "")
        if active:
            op_ctx.save_settings(operator_id, {"personality": {"active_id": active}})
        return result

    def activate_personality_for_operator(self, operator_id: str, personality_id: str) -> dict:
        self.apply_operator_context(operator_id)
        result = self.activate_personality(personality_id)
        return self._finish_operator_personality_mutation(operator_id, result)

    def save_personality_for_operator(self, operator_id: str, data: dict) -> dict:
        self.apply_operator_context(operator_id)
        return self._finish_operator_personality_mutation(operator_id, self.save_personality(data))

    def delete_personality_for_operator(self, operator_id: str, personality_id: str) -> dict:
        self.apply_operator_context(operator_id)
        return self._finish_operator_personality_mutation(
            operator_id, self.delete_personality(personality_id),
        )

    def import_personality_for_operator(self, operator_id: str, data: dict) -> dict:
        self.apply_operator_context(operator_id)
        return self._finish_operator_personality_mutation(
            operator_id, self.import_personality(data),
        )

    def import_personality_png_for_operator(self, operator_id: str, png_bytes: bytes) -> dict:
        self.apply_operator_context(operator_id)
        return self._finish_operator_personality_mutation(
            operator_id, self.import_personality_png(png_bytes),
        )


hub = VoiceHub()

from services.llm import webllm_broker  # noqa: E402

webllm_broker.set_broadcast(hub.broadcast)
