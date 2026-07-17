"""Unified settings API — per-operator persistence."""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from services.settings.catalog import (
    CLONE_MODELS,
    CUSTOM_TTS_MODELS,
    LITELLM_MODELS,
    REMARK_VISION_MODELS,
    TTS_LANGUAGES,
    WEBLLM_MODELS,
    fetch_openai_models,
)
from services.llm.api_keys import resolve_reasoning_api_key
from services.settings.public import to_public_settings
from services.settings.reasoning_normalize import uses_lm_studio_catalog
from services.settings.store import load_effective_settings
from services.voice.hub import hub

router = APIRouter(prefix="/api/voice/settings", tags=["voice-settings"])


def _operator_id(request: Request) -> str:
    op = getattr(request.state, "operator", None)
    return str(op.id) if op else ""


@router.get("")
def get_settings(request: Request) -> dict:
    oid = _operator_id(request)
    settings = load_effective_settings(oid or None)
    return {"ok": True, "settings": to_public_settings(settings)}


@router.get("/catalog")
def settings_catalog(
    request: Request,
    llm: bool = True,
    base_url: str = "",
    api_key: str = "",
    provider: str = "",
) -> dict:
    catalog: dict = {
        "barge_modes": ["smart", "instant", "off"],
        "delivery_modes": ["full", "hybrid", "off"],
        "tts_modes": ["clone", "custom"],
        "whisper_models": ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"],
        "compute_types": ["float16", "int8", "float32"],
        "stt_devices": ["cuda", "cpu"],
        "speakers": ["aiden", "vivian", "serena", "ryan", "ethan", "nico"],
        "eq_presets": [],
        "voices": [],
        "detection_modes": ["vad", "push_to_talk", "continuous"],
        "wispr_models": ["wispr-flow-1", "wispr-flow-1-fast", "wispr-flow-pro"],
        "reasoning_models": ["maya-reason-mini", "maya-reason", "maya-reason-pro"],
        "languages": ["en", "es", "fr", "de", "ja", "pt"],
        "llm_models": [],
        "litellm_models": [{"id": m, "label": m} for m in LITELLM_MODELS],
        "remark_vision_models": REMARK_VISION_MODELS,
        "webllm_models": WEBLLM_MODELS,
        "clone_models": [{"id": m, "label": m} for m in CLONE_MODELS],
        "custom_tts_models": [{"id": m, "label": m} for m in CUSTOM_TTS_MODELS],
        "tts_languages": TTS_LANGUAGES,
        "personas": ["maya", "operator", "assistant", "technical", "friendly", "professional"],
    }
    oid = _operator_id(request)
    settings = load_effective_settings(oid or None)
    reasoning = dict(settings.get("reasoning", {}) or {})
    if provider.strip():
        reasoning["provider"] = provider.strip()
    llm_base = (base_url or "").strip() or str(reasoning.get("base_url", ""))
    provider_lc = str(reasoning.get("provider", "lm_studio")).lower()
    if provider_lc == "lm_studio":
        llm_key = (api_key or "").strip() or "lm-studio"
    else:
        llm_key = (api_key or "").strip() or resolve_reasoning_api_key(reasoning, operator_id=oid or None)
    if llm and uses_lm_studio_catalog(reasoning):
        catalog["llm_models"] = fetch_openai_models(llm_base, llm_key, timeout=8.0)
    else:
        catalog["llm_models"] = []
    if not catalog["llm_models"] and reasoning.get("model"):
        mid = str(reasoning["model"])
        catalog["llm_models"] = [{"id": mid, "label": mid}]
    try:
        from eq import list_eq_presets

        catalog["eq_presets"] = list_eq_presets()
    except Exception:  # noqa: BLE001
        catalog["eq_presets"] = [{"id": "off", "label": "Off (bypass)"}]
    try:
        from server import _list_voices

        catalog["voices"] = _list_voices()
    except Exception:  # noqa: BLE001
        pass
    if hub.ready and hub.agent is not None:
        try:
            speakers = hub.agent.voice.list_speakers()
            if speakers:
                catalog["speakers"] = speakers
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "catalog": catalog}


@router.post("/health")
def llm_health(request: Request) -> dict:
    """Run passive /models + active 'Hi' probe against the reasoning LLM profile."""
    from services.llm.health import check_llm_health, invalidate_llm_health_cache

    oid = _operator_id(request)
    settings = load_effective_settings(oid or None)
    reasoning = settings.get("reasoning", {})
    invalidate_llm_health_cache()
    health = check_llm_health(reasoning if isinstance(reasoning, dict) else {}, operator_id=oid or None)
    return {"ok": True, "health": health}


@router.post("/imagine-health")
def imagine_health(request: Request) -> dict:
    """Probe comfyui-api reachability at the configured ComfyUI URL."""
    from services.discovery.registry import refresh_comfyui
    from services.imagine.health import apply_comfyui_url_from_settings, invalidate_comfyui_health_cache

    oid = _operator_id(request)
    settings = load_effective_settings(oid or None)
    invalidate_comfyui_health_cache()
    apply_comfyui_url_from_settings(settings)
    health = refresh_comfyui(settings)
    return {"ok": True, "health": health}


@router.post("")
def patch_settings(request: Request, data: dict = Body(...)) -> dict:
    from services.settings.public import to_public_settings

    patch = data.get("settings", data) if isinstance(data, dict) else {}
    oid = _operator_id(request)
    hub.apply_settings_patch(patch if isinstance(patch, dict) else {}, operator_id=oid or None)
    return {"ok": True, "settings": to_public_settings(load_effective_settings(oid or None))}
