"""Persist unified settings to maya-unified/data/settings.json."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

from services.paths import DATA_DIR, ROOT, VOICE_RUNTIME, agent_data_dir, resolve_voice_ref, resolve_runtime_file
from services.settings.schema import DEFAULT_SETTINGS, deep_merge

_PLACEHOLDER_API_KEYS = frozenset({"", "lm-studio", "vllm-local", "local-model"})


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
            reasoning = merged.get("reasoning", {})
            if str(reasoning.get("provider", "")).lower() == "webllm":
                webllm = dict(reasoning.get("webllm") or {})
                webllm["enabled"] = True
                merged["reasoning"] = {**reasoning, "webllm": webllm}
            return merged
    except (OSError, TypeError, ValueError):
        pass
    return deepcopy(DEFAULT_SETTINGS)


def _redact_reasoning_api_key(settings: dict[str, Any]) -> None:
    """Never persist real provider keys to settings.json — keep them in .env only."""
    reasoning = settings.get("reasoning")
    if not isinstance(reasoning, dict):
        return
    key = str(reasoning.get("api_key") or "").strip()
    if not key or key.lower() in _PLACEHOLDER_API_KEYS:
        return
    if key.startswith("sk-"):
        reasoning["api_key"] = "lm-studio"


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    merged = deep_merge(current, patch)
    reasoning = merged.get("reasoning", {})
    if str(reasoning.get("provider", "")).lower() == "webllm":
        webllm = dict(reasoning.get("webllm") or {})
        webllm["enabled"] = True
        merged["reasoning"] = {**reasoning, "webllm": webllm}
    _redact_reasoning_api_key(merged)
    with open(_path(), "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
    return merged


def apply_to_config(settings: dict[str, Any], *, operator_id: str | None = None) -> None:
    """Push reasoning + detection settings into qwen3 CONFIG (in-process)."""
    from config import CONFIG

    r = settings.get("reasoning", {})
    provider = str(r.get("provider", "lm_studio"))
    if provider == "webllm":
        webllm = r.get("webllm") or {}
        model_id = str(webllm.get("model_id") or "")
        if model_id:
            CONFIG.llm.model = model_id
    elif provider == "litellm":
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
        CONFIG.tts.ref_audio = resolve_voice_ref(str(voice["ref_audio"]))
    if voice.get("ref_text") is not None:
        CONFIG.tts.ref_text = str(voice["ref_text"])
    elif not CONFIG.tts.ref_text.strip():
        _load_ref_text_sidecar(CONFIG.tts)
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
    if audio.get("output_sink"):
        CONFIG.audio.output_sink = str(audio["output_sink"]).strip().lower()
    if audio.get("output_volume") is not None:
        CONFIG.audio.output_volume = float(audio["output_volume"])
    if audio.get("eq_enabled") is not None:
        CONFIG.audio.eq_enabled = bool(audio["eq_enabled"])
    if audio.get("eq_preset"):
        CONFIG.audio.eq_preset = str(audio["eq_preset"])
    if audio.get("aec_enabled") is not None:
        CONFIG.audio.aec_enabled = bool(audio["aec_enabled"])

    mem = settings.get("memory", {})
    CONFIG.memory.data_dir = str(agent_data_dir(operator_id))
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
    if CONFIG.mcp.enabled:
        CONFIG.mcp.config_file = resolve_runtime_file(CONFIG.mcp.config_file)

    runtime = settings.get("runtime", {})
    if runtime.get("orchestrator") is not None:
        CONFIG.llm.orchestrator_enabled = bool(runtime["orchestrator"])
    if runtime.get("web_tools") is not None:
        CONFIG.web.enabled = bool(runtime["web_tools"])

    disc = settings.get("discord", {})
    token = str(disc.get("token") or "").strip()
    if token:
        CONFIG.discord.token = token
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


def _load_ref_text_sidecar(tts_cfg) -> None:
    import os

    base, _ = os.path.splitext(tts_cfg.ref_audio)
    ref_dir = os.path.dirname(tts_cfg.ref_audio) or "."
    for candidate in (f"{base}.txt", os.path.join(ref_dir, "ref.txt")):
        if os.path.exists(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    tts_cfg.ref_text = fh.read().strip()
                break
            except OSError:
                pass


def _apply_reasoning_env(reasoning: dict[str, Any], *, provider: str, litellm_mode: str, litellm_model: str, base_url: str, model: str, api_key: str) -> None:
    if provider:
        reasoning["provider"] = provider
    if litellm_mode:
        litellm_cfg = dict(reasoning.get("litellm") or {})
        litellm_cfg["mode"] = litellm_mode
        reasoning["litellm"] = litellm_cfg
    if litellm_model:
        litellm_cfg = dict(reasoning.get("litellm") or {})
        litellm_cfg["model"] = litellm_model
        reasoning["model"] = litellm_model
        reasoning["litellm"] = litellm_cfg
    if base_url:
        reasoning["base_url"] = base_url
    if model and not litellm_model:
        reasoning["model"] = model
    if api_key:
        reasoning["api_key"] = api_key


def _overlay_env_vars(settings: dict[str, Any]) -> None:
    """Apply VA_* process env onto settings (gateway loads .env at startup)."""
    reasoning = settings.setdefault("reasoning", {})
    discord = settings.setdefault("discord", {})

    provider = os.environ.get("VA_LLM_PROVIDER", "").strip()
    litellm_mode = os.environ.get("VA_LLM_LITELLM_MODE", "").strip()
    litellm_model = os.environ.get("VA_LLM_LITELLM_MODEL", "").strip()
    base_url = os.environ.get("VA_LLM_BASE_URL", "").strip()
    model = os.environ.get("VA_LLM_MODEL", "").strip()
    api_key = (
        os.environ.get("OPENROUTER_API_KEY", "").strip()
        or os.environ.get("VA_LLM_API_KEY", "").strip()
    )
    _apply_reasoning_env(
        reasoning,
        provider=provider,
        litellm_mode=litellm_mode,
        litellm_model=litellm_model,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )

    token = os.environ.get("VA_DISCORD_TOKEN", "").strip()
    if token:
        discord["token"] = token
        discord["enabled"] = True
    guild = os.environ.get("VA_DISCORD_GUILD_ID", "").strip()
    if guild:
        try:
            discord["guild_id"] = int(guild)
        except ValueError:
            pass
    if os.environ.get("VA_DISCORD_AUTO_REPLY") is not None:
        discord["auto_reply"] = os.environ.get("VA_DISCORD_AUTO_REPLY", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    vol = os.environ.get("VA_DISCORD_MUSIC_VOLUME", "").strip()
    if vol:
        try:
            discord["music_volume"] = float(vol)
        except ValueError:
            pass


def _overlay_env_file(settings: dict[str, Any], env_path) -> None:
    if not env_path.is_file():
        return
    reasoning = settings.setdefault("reasoning", {})
    provider = ""
    litellm_mode = ""
    litellm_model = ""
    base_url = ""
    model = ""
    api_key = ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "VA_LLM_PROVIDER" and val:
            provider = val
        elif key == "VA_LLM_LITELLM_MODE" and val:
            litellm_mode = val
        elif key == "VA_LLM_LITELLM_MODEL" and val:
            litellm_model = val
        elif key == "VA_LLM_BASE_URL" and val:
            base_url = val
        elif key == "VA_LLM_MODEL" and val:
            model = val
        elif key == "OPENROUTER_API_KEY" and val:
            api_key = val
        elif key == "VA_LLM_API_KEY" and val and not api_key:
            api_key = val
        elif key == "VA_DISCORD_TOKEN" and val:
            disc = settings.setdefault("discord", {})
            disc["token"] = val
            disc["enabled"] = True
        elif key == "VA_DISCORD_GUILD_ID" and val:
            try:
                settings.setdefault("discord", {})["guild_id"] = int(val)
            except ValueError:
                pass
    _apply_reasoning_env(
        reasoning,
        provider=provider,
        litellm_mode=litellm_mode,
        litellm_model=litellm_model,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )


def seed_env_defaults() -> dict[str, Any]:
    """Global settings file + .env / VA_* overlays (shared runtime defaults)."""
    settings = load_settings()
    _overlay_env_file(settings, ROOT / ".env")
    if VOICE_RUNTIME.is_dir():
        _overlay_env_file(settings, VOICE_RUNTIME / ".env")
    _overlay_env_vars(settings)
    return settings


def load_effective_settings(operator_id: str | None = None) -> dict[str, Any]:
    """Operator settings with global/env fallbacks for unset fields (e.g. Discord token)."""
    base = seed_env_defaults()
    if not operator_id:
        return base
    from services.operator_voice import context as op_ctx

    operator = op_ctx.load_settings(operator_id)
    merged = deep_merge(base, operator)
    op_disc = operator.get("discord") if isinstance(operator.get("discord"), dict) else {}
    if not str((op_disc or {}).get("token") or "").strip():
        merged["discord"] = deepcopy(base.get("discord") or merged.get("discord") or {})
    return merged
