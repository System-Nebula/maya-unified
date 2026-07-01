"""Catalog helpers for settings dropdowns."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

WEBLLM_MODELS = [
    {"id": "Llama-3.1-8B-Instruct-q4f16_1-MLC", "label": "Llama 3.1 8B Instruct (q4)"},
    {"id": "Llama-3.2-3B-Instruct-q4f16_1-MLC", "label": "Llama 3.2 3B Instruct (q4)"},
    {"id": "Phi-3.5-mini-instruct-q4f16_1-MLC", "label": "Phi 3.5 mini (q4)"},
    {"id": "Qwen2.5-1.5B-Instruct-q4f16_1-MLC", "label": "Qwen 2.5 1.5B (q4)"},
    {"id": "Qwen2.5-7B-Instruct-q4f16_1-MLC", "label": "Qwen 2.5 7B (q4)"},
    {"id": "Hermes-2-Pro-Llama-3-8B-q4f16_1-MLC", "label": "Hermes 2 Pro Llama 3 8B"},
]

LITELLM_MODELS = [
    "gemini/gemini-2.0-flash",
    "gemini/gemini-2.5-flash-preview-04-17",
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "anthropic/claude-3-5-sonnet-20241022",
    "ollama/llama3.1",
    "ollama/mistral",
    "groq/llama-3.3-70b-versatile",
]

CLONE_MODELS = [
    "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
]

CUSTOM_TTS_MODELS = [
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
]

TTS_LANGUAGES = ["English", "Chinese", "Japanese", "Korean", "German", "French", "Spanish", "Italian", "Portuguese", "Russian"]


def fetch_openai_models(base_url: str, api_key: str, timeout: float = 3.0) -> list[dict[str, str]]:
    base = (base_url or "").rstrip("/")
    if not base:
        return []
    url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key or 'lm-studio'}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        items = data.get("data") or data.get("models") or []
        out: list[dict[str, str]] = []
        for m in items:
            mid = m.get("id") if isinstance(m, dict) else str(m)
            if mid:
                out.append({"id": mid, "label": mid})
        out.sort(key=lambda x: x["id"].lower())
        return out
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
