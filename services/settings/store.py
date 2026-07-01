"""Persist unified settings to maya-unified/data/settings.json."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

from services.paths import DATA_DIR, VOICE_RUNTIME, agent_data_dir
from services.settings.schema import DEFAULT_SETTINGS, deep_merge


def _path() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return str(DATA_DIR / "settings.json")


def load_settings() -> dict[str, Any]:
    path = _path()
    if not os.path.isfile(path):
        return deepcopy(DEFAULT_SETTINGS)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            merged = deep_merge(DEFAULT_SETTINGS, data)
            disc = merged.get("discord", {})
            if str(disc.get("token") or "").strip() and not disc.get("enabled"):
                merged["discord"] = {**disc, "enabled": True}
            return merged
    except (OSError, TypeError, ValueError):
        pass
    return deepcopy(DEFAULT_SETTINGS)


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    merged = deep_merge(current, patch)
    with open(_path(), "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
    return merged


def apply_to_config(settings: dict[str, Any]) -> None:
    """Push reasoning + detection settings into qwen3 CONFIG (in-process)."""
    from config import CONFIG

    r = settings.get("reasoning", {})
    provider = str(r.get("provider", "lm_studio"))
    if provider == "litellm":
        litellm_cfg = r.get("litellm") or {}
        if str(litellm_cfg.get("mode", "sdk")) == "proxy" and r.get("base_url"):
            CONFIG.llm.base_url = str(r["base_url"])
        CONFIG.llm.model = str(litellm_cfg.get("model") or r.get("model", CONFIG.llm.model))
    else:
        if r.get("base_url"):
            CONFIG.llm.base_url = str(r["base_url"])
        if r.get("model"):
            CONFIG.llm.model = str(r["model"])
    if r.get("api_key") is not None:
        CONFIG.llm.api_key = str(r["api_key"])
    if r.get("temperature") is not None:
        CONFIG.llm.temperature = float(r["temperature"])
    if r.get("max_tokens") is not None:
        CONFIG.llm.max_tokens = int(r["max_tokens"])
    if r.get("top_p") is not None:
        CONFIG.llm.top_p = float(r["top_p"])
    if r.get("reasoning_effort") is not None:
        CONFIG.llm.reasoning_effort = str(r["reasoning_effort"])
    if r.get("disable_thinking") is not None:
        CONFIG.llm.disable_thinking = bool(r["disable_thinking"])

    d = settings.get("dictation", {})
    if d.get("whisper_model"):
        CONFIG.stt.whisper_model = str(d["whisper_model"])
    if d.get("language"):
        CONFIG.stt.language = str(d["language"])
    if d.get("device"):
        CONFIG.stt.device = str(d["device"])
    if d.get("compute_type"):
        CONFIG.stt.whisper_compute_type = str(d["compute_type"])

    det = settings.get("detection", {})
    if det.get("barge_mode"):
        CONFIG.audio.barge_mode = str(det["barge_mode"])
    if det.get("barge_in") is not None:
        CONFIG.audio.barge_in = bool(det["barge_in"])
    if det.get("vad_aggressiveness") is not None:
        CONFIG.vad.aggressiveness = int(det["vad_aggressiveness"])
    if det.get("silence_ms") is not None:
        CONFIG.vad.silence_ms = int(det["silence_ms"])
    if det.get("min_speech_ms") is not None:
        CONFIG.vad.min_speech_ms = int(det["min_speech_ms"])

    deliv = settings.get("delivery", {})
    if deliv.get("tts_mode"):
        CONFIG.tts.mode = str(deliv["tts_mode"])
    if deliv.get("delivery"):
        CONFIG.tts.delivery = str(deliv["delivery"])
    if deliv.get("auto_instruct") is not None:
        CONFIG.tts.auto_instruct = bool(deliv["auto_instruct"])
    if deliv.get("xvec_only") is not None:
        CONFIG.tts.xvec_only = bool(deliv["xvec_only"])
    if deliv.get("instruct") is not None:
        CONFIG.tts.instruct = str(deliv["instruct"])

    voice = settings.get("voice", {})
    if voice.get("ref_audio"):
        CONFIG.tts.ref_audio = str(voice["ref_audio"])
    if voice.get("ref_text") is not None:
        CONFIG.tts.ref_text = str(voice["ref_text"])
    if voice.get("speaker"):
        CONFIG.tts.speaker = str(voice["speaker"])
    if voice.get("clone_model"):
        CONFIG.tts.clone_model = str(voice["clone_model"])
    if voice.get("custom_model"):
        CONFIG.tts.custom_model = str(voice["custom_model"])
    if voice.get("language"):
        CONFIG.tts.language = str(voice["language"])
    if voice.get("temperature") is not None:
        CONFIG.tts.temperature = float(voice["temperature"])
    if voice.get("top_k") is not None:
        CONFIG.tts.top_k = int(voice["top_k"])
    if voice.get("seed") is not None:
        CONFIG.tts.seed = int(voice["seed"])
    if voice.get("warmup") is not None:
        CONFIG.tts.warmup = bool(voice["warmup"])
    if voice.get("device"):
        CONFIG.tts.device = str(voice["device"])

    audio = settings.get("audio", {})
    if audio.get("output_volume") is not None:
        CONFIG.audio.output_volume = float(audio["output_volume"])
    if audio.get("eq_enabled") is not None:
        CONFIG.audio.eq_enabled = bool(audio["eq_enabled"])
    if audio.get("eq_preset"):
        CONFIG.audio.eq_preset = str(audio["eq_preset"])
    if audio.get("aec_enabled") is not None:
        CONFIG.audio.aec_enabled = bool(audio["aec_enabled"])

    mem = settings.get("memory", {})
    CONFIG.memory.data_dir = str(agent_data_dir())
    if mem.get("enabled") is not None:
        CONFIG.memory.enabled = bool(mem["enabled"])
    if mem.get("write_approval") is not None:
        CONFIG.memory.write_approval = bool(mem["write_approval"])
    if mem.get("cognitive_enabled") is not None:
        CONFIG.memory.cognitive_enabled = bool(mem["cognitive_enabled"])
    if mem.get("prefetch") is not None:
        CONFIG.memory.prefetch = bool(mem["prefetch"])

    tools = settings.get("tools", {})
    if tools.get("enabled") is not None:
        CONFIG.tools.enabled = bool(tools["enabled"])
    if tools.get("max_rounds") is not None:
        CONFIG.tools.max_rounds = int(tools["max_rounds"])
    if tools.get("mode"):
        CONFIG.tools.mode = str(tools["mode"])
    if tools.get("mcp_enabled") is not None:
        CONFIG.mcp.enabled = bool(tools["mcp_enabled"])

    runtime = settings.get("runtime", {})
    if runtime.get("orchestrator") is not None:
        CONFIG.llm.orchestrator_enabled = bool(runtime["orchestrator"])
    if runtime.get("web_tools") is not None:
        CONFIG.web.enabled = bool(runtime["web_tools"])

    disc = settings.get("discord", {})
    token = str(disc.get("token") or "").strip()
    if token:
        CONFIG.discord.token = token
        # Token saved ⇒ bot should run (toggle off clears token in UI).
        CONFIG.discord.enabled = True
    elif disc.get("enabled") is not None:
        CONFIG.discord.enabled = bool(disc["enabled"])
    if disc.get("guild_id"):
        CONFIG.discord.guild_id = int(disc["guild_id"])
    if disc.get("auto_reply") is not None:
        CONFIG.discord.auto_reply = bool(disc["auto_reply"])
    if disc.get("music_volume") is not None:
        CONFIG.discord.music_volume = float(disc["music_volume"])

    vts = settings.get("vts", {})
    if vts.get("enabled") is not None:
        CONFIG.vts.enabled = bool(vts["enabled"])
    if vts.get("host"):
        CONFIG.vts.host = str(vts["host"])
    if vts.get("port") is not None:
        CONFIG.vts.port = int(vts["port"])
    if vts.get("expressions") is not None:
        CONFIG.vts.expressions = bool(vts["expressions"])
    if vts.get("auto_express") is not None:
        CONFIG.vts.expressions = bool(vts["auto_express"])
    if vts.get("mouth_gain") is not None:
        CONFIG.vts.mouth_gain = float(vts["mouth_gain"])
    if vts.get("mouth_smoothing") is not None:
        CONFIG.vts.mouth_smoothing = float(vts["mouth_smoothing"])
    if vts.get("mouth_fps") is not None:
        CONFIG.vts.mouth_fps = int(vts["mouth_fps"])


def seed_env_defaults() -> dict[str, Any]:
    """Merge .env / VA_* into settings on first load."""
    settings = load_settings()
    if VOICE_RUNTIME.is_dir():
        env_path = VOICE_RUNTIME / ".env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == "VA_LLM_BASE_URL" and val:
                    settings["reasoning"]["base_url"] = val
                elif key == "VA_LLM_MODEL" and val:
                    settings["reasoning"]["model"] = val
                elif key == "VA_LLM_API_KEY" and val:
                    settings["reasoning"]["api_key"] = val
                elif key == "VA_DISCORD_TOKEN" and val:
                    settings["discord"]["token"] = val
                    settings["discord"]["enabled"] = True
    return settings
