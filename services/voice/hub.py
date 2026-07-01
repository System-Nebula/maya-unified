"""Voice agent hub — extends qwen3 Hub with unified settings + LLM providers."""

from __future__ import annotations

import os
import threading
import urllib.error
import urllib.request

from server import Hub

from services.llm.provider import create_llm_client, swap_agent_llm
from services.paths import DATA_DIR, VOICE_AGENT
from services.voice.data_migration import migrate_qwen3_data_to_unified
from services.settings.store import apply_to_config, load_settings, save_settings

# Settings sections that register tools at VoiceAgent init — require reload.
_RELOAD_SECTIONS = frozenset({"discord", "tools", "memory", "runtime"})


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
    """Map settings diff → qwen3 hub.set_config keys (only changed values)."""
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
    """Return (ok, error_message) for an OpenAI-compatible /v1/models probe."""
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
    except urllib.error.URLError as exc:
        return False, (
            f"Cannot reach LLM at {base}. "
            "Start LM Studio and load a model, or update Settings → Reasoning."
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


class VoiceHub(Hub):
    last_error: str = ""

    def unload_agent(self) -> None:
        """Stop session and drop the agent so load_agent can run again."""
        try:
            self.stop()
        except Exception:  # noqa: BLE001
            pass
        self.agent = None
        self.ready = False
        self.status = "idle"
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
            settings = load_settings()
            apply_to_config(settings)
            from services.discord.unified_bot import apply_discord_env

            apply_discord_env(settings)
            migrate_qwen3_data_to_unified()
            os.makedirs(DATA_DIR, exist_ok=True)
            os.environ["VA_DATA_DIR"] = str(DATA_DIR)
            if VOICE_AGENT.is_dir():
                os.chdir(str(VOICE_AGENT))

            from agent import VoiceAgent

            self.broadcast({"type": "status", "value": "loading"})
            agent = VoiceAgent(mode="vad", on_event=self.broadcast)
            agent.llm = create_llm_client()
            swap_agent_llm(agent)
            self.agent = agent
            from services.discord.patch_agent import patch_voice_agent

            patch_voice_agent(agent)
            from config import CONFIG

            self.current_voice = os.path.basename(CONFIG.tts.ref_audio)
            self.ready = True
            self.broadcast({"type": "ready", "value": True})
            self.broadcast({"type": "status", "value": "idle"})
            self.broadcast({"type": "settings", "unified": load_settings()})
        except Exception as exc:  # noqa: BLE001
            self.ready = False
            self.last_error = str(exc)
            self.broadcast({"type": "error", "text": f"Failed to load agent: {exc}"})
            self.broadcast({"type": "status", "value": "error"})

    def apply_settings_patch(self, patch: dict) -> dict:
        previous = load_settings()
        merged = save_settings(patch if isinstance(patch, dict) else {})
        if merged == previous:
            return merged

        apply_to_config(merged)
        from services.discord.unified_bot import apply_discord_env

        apply_discord_env(merged)
        needs_reload = any(_section_changed(previous, merged, section) for section in _RELOAD_SECTIONS)
        if needs_reload and (self.ready or self.agent is not None):
            self.request_agent_reload()
            self.broadcast({"type": "settings", "unified": merged})
            return merged
        if self.ready and self.agent is not None:
            if _section_changed(previous, merged, "reasoning"):
                swap_agent_llm(self.agent)
            live = _build_live_diff(previous, merged)
            if live:
                self.set_config(live)
            new_pid = str(_nested_get(merged, "personality", "active_id") or "")
            old_pid = str(_nested_get(previous, "personality", "active_id") or "")
            if new_pid and new_pid != old_pid:
                self.activate_personality(new_pid)
        self.broadcast({"type": "settings", "unified": merged})
        return merged

    def get_config(self) -> dict:
        out = super().get_config()
        out["unified_settings"] = load_settings()
        if self.last_error:
            out["agent_error"] = self.last_error
        return out

    def llm_status(self) -> dict:
        from config import CONFIG

        settings = load_settings()
        reasoning = settings.get("reasoning", {})
        ok, err = _ping_llm(CONFIG.llm.base_url, CONFIG.llm.api_key)
        return {
            "ok": ok,
            "provider": str(reasoning.get("provider", "lm_studio")),
            "base_url": CONFIG.llm.base_url,
            "model": CONFIG.llm.model,
            "error": err or None,
        }

    def chat_text(self, text: str) -> dict:
        """Text-only turn via server LLM (no TTS) for Conversation panel."""
        if not self.ready or self.agent is None:
            return {"ok": False, "error": self.last_error or "agent not ready"}
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty message"}
        from config import CONFIG

        llm_ok, llm_err = _ping_llm(CONFIG.llm.base_url, CONFIG.llm.api_key)
        if not llm_ok:
            return {"ok": False, "error": llm_err}
        try:
            self.broadcast({"type": "status", "value": "thinking"})
            self.broadcast({"type": "user", "text": text})
            messages = self.agent._build_messages(text)  # noqa: SLF001
            parts: list[str] = []
            for chunk in self.agent.llm.stream_messages(messages):
                parts.append(chunk)
                self.broadcast({"type": "ai", "text": chunk})
            reply = "".join(parts).strip()
            self.broadcast({"type": "status", "value": "idle"})
            return {"ok": True, "text": reply}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "connection" in msg.lower() or "connect" in msg.lower():
                msg = (
                    f"LLM connection failed ({CONFIG.llm.base_url}). "
                    "Is LM Studio running with a model loaded?"
                )
            self.broadcast({"type": "status", "value": "idle"})
            self.broadcast({"type": "error", "text": msg})
            return {"ok": False, "error": msg}


hub = VoiceHub()
