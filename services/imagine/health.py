"""ComfyUI / comfyui-api connection health checks (facade over discovery)."""

from __future__ import annotations

from typing import Any

from services.discovery.comfyui import (
    apply_comfyui_url_from_settings,
    comfyui_ready_from_health,
    discover_comfyui_local,
    format_comfyui_unavailable_error,
    get_cached_comfyui_health,
    invalidate_comfyui_health_cache,
    probe_comfyui_url,
    probe_zimage_weights,
    resolve_comfyui_native_url,
    resolve_comfyui_url,
)

__all__ = [
    "apply_comfyui_url_from_settings",
    "check_comfyui_health",
    "comfyui_ready_from_health",
    "discover_comfyui_local",
    "format_comfyui_unavailable_error",
    "get_cached_comfyui_health",
    "invalidate_comfyui_health_cache",
    "probe_zimage_weights",
    "resolve_comfyui_native_url",
    "resolve_comfyui_url",
]


def check_comfyui_health(
    url: str | None = None,
    *,
    settings: dict[str, Any] | None = None,
    run_probe: bool = True,
) -> dict[str, Any]:
    if url is not None:
        return dict(probe_comfyui_url(url, run_probe=run_probe))
    return dict(discover_comfyui_local(settings, run_probe=run_probe, adopt=False))
