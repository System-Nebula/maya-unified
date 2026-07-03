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

from services.llm.provider import create_llm_client, is_webllm_provider, swap_agent_llm
from services.operator_voice.paths import operator_data_dir as op_data_dir
from services.paths import DATA_DIR, VOICE_RUNTIME
from services.voice.data_migration import migrate_qwen3_data_to_unified
from services.settings.store import apply_to_config, load_effective_settings, load_settings as load_global_settings, save_settings as save_global_settings

_RELOAD_SECTIONS = frozenset({"discord", "tools", "memory", "runtime"})
_inference_lock = threading.Lock()


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
        global_types = frozenset({"ready", "status", "error"})
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
            settings = load_global_settings()
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

            self.current_voice = os.path.basename(CONFIG.tts.ref_audio)
            self.ready = True
            self.broadcast({"type": "ready", "value": True})
            self.broadcast({"type": "status", "value": "idle"})
        except Exception as exc:  # noqa: BLE001
            self.ready = False
            self.last_error = str(exc)
            self.broadcast({"type": "error", "text": f"Failed to load agent: {exc}"})
            self.broadcast({"type": "status", "value": "error"})

    def _agent_event(self, event: dict) -> None:
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

        apply_to_config(merged, operator_id=operator_id)
        from services.discord.unified_bot import apply_discord_env

        apply_discord_env(merged)
        if _section_changed(previous, merged, "reasoning"):
            from services.llm.health import invalidate_llm_health_cache

            invalidate_llm_health_cache()
        needs_reload = any(_section_changed(previous, merged, s) for s in _RELOAD_SECTIONS)
        if needs_reload and (self.ready or self.agent is not None):
            self.request_agent_reload()
            self.broadcast({"type": "settings", "unified": merged}, operator_id=operator_id)
            return merged
        if self.ready and self.agent is not None:
            if operator_id:
                self.apply_operator_context(operator_id)
            if _section_changed(previous, merged, "reasoning"):
                swap_agent_llm(self.agent)
            live = _build_live_diff(previous, merged)
            if live:
                self.set_config(live)
            new_pid = str(_nested_get(merged, "personality", "active_id") or "")
            old_pid = str(_nested_get(previous, "personality", "active_id") or "")
            if new_pid and new_pid != old_pid:
                self.activate_personality(new_pid)
        self.broadcast({"type": "settings", "unified": merged}, operator_id=operator_id)
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
            if role == "user":
                turns.append({"role": "operator", "text": content})
            elif role == "assistant":
                turns.append({"role": "maya", "text": content})
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
            self.broadcast({"type": "status", "value": "thinking"}, operator_id=operator_id)
            self.broadcast({"type": "user", "text": text}, operator_id=operator_id)
            system = (CONFIG.llm.system_prompt or "You are Maya, a helpful assistant.").strip()
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ]
            client = create_llm_client()
            parts: list[str] = []
            with _inference_lock:
                for chunk in client.stream_messages(messages):
                    parts.append(chunk)
                    self.broadcast({"type": "ai", "text": chunk}, operator_id=operator_id)
            reply = "".join(parts).strip()
            self.broadcast({"type": "status", "value": "idle"}, operator_id=operator_id)
            return {"ok": True, "text": reply, "mode": "basic"}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
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
            self.broadcast({"type": "status", "value": "thinking"}, operator_id=operator_id)
            self.broadcast({"type": "user", "text": text}, operator_id=operator_id)
            messages = self.agent._build_messages(text, history_override=history_override)  # noqa: SLF001
            parts: list[str] = []
            with _inference_lock:
                for chunk in self.agent.llm.stream_messages(messages):
                    parts.append(chunk)
                    self.broadcast({"type": "ai", "text": chunk}, operator_id=operator_id)
            reply = "".join(parts).strip()
            if reply:
                if operator_id:
                    from services.operator_voice import context as op_ctx

                    op_ctx.append_turn(operator_id, "user", text)
                    op_ctx.append_turn(operator_id, "assistant", reply)
                else:
                    self.agent.history.append({"role": "user", "content": text})
                    self.agent.history.append({"role": "assistant", "content": reply})
            self.broadcast({"type": "status", "value": "idle"}, operator_id=operator_id)
            return {"ok": True, "text": reply}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
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
            self.broadcast({"type": "status", "value": "thinking"}, room_id=room_id)
            self.broadcast({"type": "user", "text": user_line}, room_id=room_id)
            messages = self.agent._build_messages(user_line, history_override=history)  # noqa: SLF001
            parts: list[str] = []
            with _inference_lock:
                for chunk in self.agent.llm.stream_messages(messages):
                    parts.append(chunk)
                    self.broadcast({"type": "ai", "text": chunk}, room_id=room_id)
            reply = "".join(parts).strip()
            self.broadcast({"type": "status", "value": "idle"}, room_id=room_id)
            return {"ok": True, "text": reply}
        except Exception as exc:  # noqa: BLE001
            self.broadcast({"type": "status", "value": "idle"}, room_id=room_id)
            return {"ok": False, "error": str(exc)}

    def speak_text(self, text: str, *, instruct: str | None = None, operator_id: str | None = None) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": self.last_error or "agent not ready"}
        if operator_id:
            self.apply_operator_context(operator_id)
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty text"}
        instruct = (instruct or "").strip() or None

        def _run() -> None:
            try:
                with _inference_lock:
                    self.agent.speak_preview(text, instruct=instruct)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.broadcast({"type": "status", "value": "idle"}, operator_id=operator_id)
                self.broadcast({"type": "tts_error", "text": msg}, operator_id=operator_id)

        threading.Thread(target=_run, daemon=True, name="tts-preview").start()
        return {"ok": True}

    def start(self, operator_id: str | None = None) -> dict:
        if not self.ready or self.agent is None:
            return {"ok": False, "error": "agent not ready"}
        if not operator_id:
            self.agent.start_session()
            return {"ok": True}
        lease = VoiceLease(kind="operator", context_id=str(operator_id), speaker_id=str(operator_id))
        denied = self._acquire_lease(lease)
        if not denied.get("ok"):
            return {
                "ok": False,
                "error": denied.get("error", "voice_in_use"),
                "owner": denied.get("owner"),
            }
        self.apply_operator_context(operator_id)
        self.agent.start_session()
        return {"ok": True}

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
