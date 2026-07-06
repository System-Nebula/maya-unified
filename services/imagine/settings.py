"""Imagine / ComfyUI settings helpers and legacy migration."""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

DEFAULT_IMAGINE_URL = "http://127.0.0.1:3030"
DEFAULT_IMAGINE_MODEL = "zit"
DEFAULT_REMARK_VISION_MODEL = "openrouter/minimax/minimax-m3"
IMAGINE_DEFAULT_MODEL_CHOICES = ("zit", "krea2", "ideogram-local")
LOCAL_COMFY_MODELS = frozenset({"zit", "z-image", "krea2", "krea-2", "ideogram-local", "comfyui"})


def resolve_imagine_default_model(settings: dict[str, Any] | None) -> str:
    """Resolve dashboard/chat default imagine model from env then settings."""
    env_model = os.getenv("MAYA_IMAGINE_DEFAULT_MODEL", "").strip().lower()
    if env_model:
        return env_model
    imagine = get_imagine_settings(settings)
    model = str(imagine.get("default_model") or DEFAULT_IMAGINE_MODEL).strip().lower()
    if model not in IMAGINE_DEFAULT_MODEL_CHOICES:
        return DEFAULT_IMAGINE_MODEL
    return model


def resolve_imagine_model(model: str | None, settings: dict[str, Any] | None) -> str:
    """Use explicit model when provided, otherwise Settings → Imagine default."""
    explicit = str(model or "").strip().lower()
    if explicit:
        return explicit
    return resolve_imagine_default_model(settings)


def get_imagine_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Return normalized imagine settings with discord legacy fallback."""
    settings = settings or {}
    imagine = dict(settings.get("imagine") or {})
    disc = dict(settings.get("discord") or {})

    enabled = imagine.get("enabled")
    if enabled is None:
        enabled = disc.get("imagine_enabled", False)

    url = str(imagine.get("comfyui_url") or disc.get("comfyui_url") or DEFAULT_IMAGINE_URL).strip()
    default_model = str(imagine.get("default_model") or DEFAULT_IMAGINE_MODEL).strip().lower()
    if default_model not in IMAGINE_DEFAULT_MODEL_CHOICES:
        default_model = DEFAULT_IMAGINE_MODEL
    remark_enabled = imagine.get("remark_enabled")
    if remark_enabled is None:
        remark_enabled = True
    remark_vision_model = str(imagine.get("remark_vision_model") or "").strip()
    critique_vision_model = str(
        imagine.get("critique_vision_model") or remark_vision_model
    ).strip()
    return {
        "enabled": bool(enabled),
        "comfyui_url": url.rstrip("/") or DEFAULT_IMAGINE_URL,
        "default_model": default_model,
        "remark_enabled": bool(remark_enabled),
        "remark_vision_model": remark_vision_model,
        "director_enabled": bool(imagine.get("director_enabled", True)),
        "director_max_iterations": int(imagine.get("director_max_iterations") or 3),
        "director_multi_critic": bool(imagine.get("director_multi_critic", True)),
        "critique_vision_model": critique_vision_model,
    }


def migrate_imagine_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Promote legacy discord.imagine_* into settings.imagine when missing."""
    out = deepcopy(settings)
    imagine = dict(out.get("imagine") or {})
    disc = dict(out.get("discord") or {})

    if "enabled" not in imagine and "imagine_enabled" in disc:
        imagine["enabled"] = bool(disc.get("imagine_enabled"))
    if not str(imagine.get("comfyui_url") or "").strip() and disc.get("comfyui_url"):
        imagine["comfyui_url"] = str(disc["comfyui_url"]).strip().rstrip("/")

    if "enabled" not in imagine:
        imagine["enabled"] = False
    if not str(imagine.get("comfyui_url") or "").strip():
        imagine["comfyui_url"] = DEFAULT_IMAGINE_URL
    if not str(imagine.get("default_model") or "").strip():
        imagine["default_model"] = DEFAULT_IMAGINE_MODEL
    if "remark_enabled" not in imagine:
        imagine["remark_enabled"] = True
    if "remark_vision_model" not in imagine:
        imagine["remark_vision_model"] = DEFAULT_REMARK_VISION_MODEL
    if "director_enabled" not in imagine:
        imagine["director_enabled"] = True
    if "director_max_iterations" not in imagine:
        imagine["director_max_iterations"] = 3
    if "director_multi_critic" not in imagine:
        imagine["director_multi_critic"] = True
    if "critique_vision_model" not in imagine:
        imagine["critique_vision_model"] = imagine.get("remark_vision_model") or DEFAULT_REMARK_VISION_MODEL

    out["imagine"] = imagine
    return out
