"""Unified settings schema — extends maya-public OperatorVoiceSettings with qwen3 runtime."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "audio": {
        "input_device": None,
        "output_device": None,
        "output_sink": "browser",
        "output_volume": 1.0,
        "eq_enabled": True,
        "eq_preset": "off",
        "eq_bands": [],
        "aec_enabled": True,
    },
    "detection": {
        "barge_mode": "smart",
        "barge_in": True,
        "vad_aggressiveness": 2,
        "silence_ms": 500,
        "min_speech_ms": 250,
        "detection_mode": "vad",
        "vad_threshold": 0.02,
        "vad_hangover_ms": 600,
    },
    "dictation": {
        "whisper_model": "small.en",
        "language": "en",
        "device": "cuda",
        "compute_type": "float16",
        "wispr_model": "wispr-flow-1",
        "auto_punctuation": True,
        "filler_removal": True,
        "noise_suppression": True,
    },
    "reasoning": {
        "provider": "lm_studio",
        "base_url": "http://localhost:1234/v1",
        "api_key": "lm-studio",
        "model": "local-model",
        "temperature": 0.6,
        "max_tokens": 220,
        "top_p": 0.9,
        "reasoning_effort": "",
        "disable_thinking": True,
        "vision_capable": "auto",
        "reasoning_model": "maya-reason-mini",
        "persona": "maya",
        "litellm": {
            "mode": "sdk",
            "model": "gemini/gemini-2.0-flash",
        },
        "webllm": {
            "enabled": False,
            "model_id": "Llama-3.1-8B-Instruct-q4f16_1-MLC",
            "use_for": ["conversation"],
        },
    },
    "personality": {
        "active_id": "",
    },
    "memory": {
        "enabled": True,
        "write_approval": False,
        "cognitive_enabled": True,
        "prefetch": True,
    },
    "tools": {
        "enabled": True,
        "mode": "auto",
        "max_rounds": 3,
        "mcp_enabled": True,
    },
    "imagine": {
        "enabled": False,
        "comfyui_url": "http://127.0.0.1:3030",
        "default_model": "zit",
        "remark_enabled": True,
        "remark_vision_model": "openrouter/minimax/minimax-m3",
        "director_enabled": True,
        "director_max_iterations": 3,
        "director_multi_critic": True,
        "critique_vision_model": "",
    },
    "discord": {
        "enabled": False,
        "token": "",
        "guild_id": "",
        "auto_reply": True,
        "attach_voice": True,
        "music_volume": 0.85,
        "voice_channel_aliases": {},
        "default_voice_channel": "",
        "youtube_cookies_browser": "",
        "youtube_cookies_file": "",
    },
    "bandcamp": {
        "enabled": True,
        "username": "",
    },
    "platform": {
        "database_url": "",
        "otel_enabled": False,
    },
    "vts": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8001,
        "expressions": True,
        "auto_express": True,
        "mouth_gain": 6.0,
        "mouth_smoothing": 0.5,
        "mouth_fps": 60,
    },
    "vrm": {
        "enabled": True,
        "model": "Yuki.vrm",
        "lip_sync_mode": "viseme",
        "mouth_gain": 6.0,
        "mouth_smoothing": 0.5,
        "look_at_camera": True,
        "camera_distance": 1.8,
        "idle_enabled": True,
        "idle_animation": "Idle.fbx",
        "idle_variants": [],
        "idle_variant_min_s": 10,
        "idle_variant_max_s": 28,
        "background_preset": "default",
        "background_image": "",
    },
    "delivery": {
        "tts_mode": "clone",
        "delivery": "full",
        "auto_instruct": True,
        "xvec_only": True,
        "instruct": "",
    },
    "voice": {
        "ref_audio": "voices/ref.wav",
        "ref_text": "",
        "speaker": "aiden",
        "clone_model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "custom_model": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "language": "English",
        "temperature": 0.7,
        "top_k": 40,
        "seed": 1234,
        "warmup": False,
        "device": "cuda",
    },
    "runtime": {
        "orchestrator": True,
        "web_tools": True,
    },
}


def deep_merge(base: dict, patch: dict) -> dict:
    out = deepcopy(base)
    for key, val in patch.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out
