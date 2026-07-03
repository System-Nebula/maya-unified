"""Unified settings API — per-operator persistence."""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from services.settings.catalog import (
    CLONE_MODELS,
    CUSTOM_TTS_MODELS,
    LITELLM_MODELS,
    TTS_LANGUAGES,
    WEBLLM_MODELS,
    fetch_openai_models,
)
from services.settings.store import load_effective_settings
from services.voice.hub import hub

router = APIRouter(prefix="/api/voice/settings", tags=["voice-settings"])


def _operator_id(request: Request) -> str:
    op = getattr(request.state, "operator", None)
    return str(op.id) if op else ""


@router.get("")
def get_settings(request: Request) -> dict:
    oid = _operator_id(request)
    if oid:
        return {"ok": True, "settings": load_effective_settings(oid)}
    return {"ok": True, "settings": load_effective_settings(None)}


@router.get("/catalog")
def settings_catalog(request: Request, llm: bool = True) -> dict:
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
        "webllm_models": WEBLLM_MODELS,
        "clone_models": [{"id": m, "label": m} for m in CLONE_MODELS],
        "custom_tts_models": [{"id": m, "label": m} for m in CUSTOM_TTS_MODELS],
        "tts_languages": TTS_LANGUAGES,
        "personas": ["maya", "operator", "assistant", "technical", "friendly", "professional"],
    }
    oid = _operator_id(request)
    settings = load_effective_settings(oid or None)
    reasoning = settings.get("reasoning", {})
    if llm:
        catalog["llm_models"] = fetch_openai_models(
            str(reasoning.get("base_url", "")),
            str(reasoning.get("api_key", "")),
            timeout=0.75,
        )
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
    health = check_llm_health(reasoning if isinstance(reasoning, dict) else {})
    return {"ok": True, "health": health}


@router.post("")
def patch_settings(request: Request, data: dict = Body(...)) -> dict:
    patch = data.get("settings", data) if isinstance(data, dict) else {}
    oid = _operator_id(request)
    merged = hub.apply_settings_patch(patch if isinstance(patch, dict) else {}, operator_id=oid or None)
    return {"ok": True, "settings": load_effective_settings(oid or None)}
