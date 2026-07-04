"""Imagine / ComfyUI settings helpers and legacy migration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_IMAGINE_URL = "http://127.0.0.1:3030"


def get_imagine_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Return normalized imagine settings with discord legacy fallback."""
    settings = settings or {}
    imagine = dict(settings.get("imagine") or {})
    disc = dict(settings.get("discord") or {})

    enabled = imagine.get("enabled")
    if enabled is None:
        enabled = disc.get("imagine_enabled", False)

    url = str(imagine.get("comfyui_url") or disc.get("comfyui_url") or DEFAULT_IMAGINE_URL).strip()
    return {
        "enabled": bool(enabled),
        "comfyui_url": url.rstrip("/") or DEFAULT_IMAGINE_URL,
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

    out["imagine"] = imagine
    return out
