"""ComfyUI / comfyui-api discovery and health probes."""

from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from services.discovery.models import ServiceHealth

log = logging.getLogger("maya-unified.discovery.comfyui")

HEALTH_CACHE_TTL_S = 90.0
DEFAULT_CANDIDATE_PORTS = (3000, 3030)
DEFAULT_NATIVE_PORT = 8188
ZIMAGE_WEIGHTS: dict[str, tuple[str, str]] = {
    "unet": ("UNETLoader", "z_image_turbo_bf16.safetensors"),
    "clip": ("CLIPLoader", "qwen_3_4b.safetensors"),
    "vae": ("VAELoader", "ae.safetensors"),
}
_health_cache: dict[str, tuple[float, ServiceHealth]] = {}


def resolve_configured_comfyui_url(settings: dict[str, Any] | None = None) -> str:
    env_url = os.getenv("COMFYUI_API_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    if settings:
        from services.imagine.settings import get_imagine_settings

        url = get_imagine_settings(settings).get("comfyui_url") or ""
        if url:
            return str(url).rstrip("/")
    return "http://127.0.0.1:3030"


def discovery_candidate_ports() -> list[int]:
    raw = os.getenv("MAYA_COMFY_DISCOVERY_PORTS", "").strip()
    if not raw:
        return list(DEFAULT_CANDIDATE_PORTS)
    ports: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ports.append(int(part))
        except ValueError:
            continue
    return ports or list(DEFAULT_CANDIDATE_PORTS)


def _is_wrong_app_html(text: str) -> bool:
    """Detect HTML from non-comfyui apps (e.g. Next.js on :3000). Swagger UI is valid."""
    head = text[:512].lower()
    if "swagger" in head or "swagger-ui" in head:
        return False
    return head.startswith("<!doctype") or "<html" in head or "_next/static" in head


def resolve_comfyui_native_url(api_url: str) -> str:
    """ComfyUI native API URL (object_info) from comfyui-api base URL."""
    env_url = os.getenv("COMFYUI_NATIVE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")
    parsed = urlparse(api_url)
    host = parsed.hostname or "127.0.0.1"
    return f"http://{host}:{DEFAULT_NATIVE_PORT}"


def _loader_options(object_info: dict[str, Any], loader: str, input_key: str) -> list[str]:
    node = object_info.get(loader) or {}
    required = (node.get("input") or {}).get("required") or {}
    raw = required.get(input_key)
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        return [str(item) for item in raw[0]]
    return []


def probe_zimage_weights(native_url: str) -> dict[str, Any]:
    """Check whether Z-Image Turbo weights are visible to ComfyUI's loader dropdowns."""
    base = native_url.rstrip("/")
    input_keys = {
        "UNETLoader": "unet_name",
        "CLIPLoader": "clip_name",
        "VAELoader": "vae_name",
    }
    missing: list[str] = []
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            object_info: dict[str, Any] = {}
            for loader, input_key in input_keys.items():
                resp = client.get(f"{base}/object_info/{loader}")
                if resp.status_code >= 400:
                    return {
                        "ok": False,
                        "missing": list(ZIMAGE_WEIGHTS.values()),
                        "detail": f"Cannot query ComfyUI {loader} at {base}/object_info/{loader}",
                    }
                payload = resp.json()
                if isinstance(payload, dict):
                    object_info.update(payload)

            for label, (loader, filename) in ZIMAGE_WEIGHTS.items():
                options = _loader_options(object_info, loader, input_keys[loader])
                if filename not in options:
                    missing.append(filename)

            if missing:
                return {
                    "ok": False,
                    "missing": missing,
                    "detail": (
                        "ComfyUI reachable but Z-Image weights not visible "
                        f"({', '.join(missing)}). Check docker volume mounts "
                        "(expect host ~/ComfyUI/models → /opt/ComfyUI/models). "
                        "See infra/comfyui/README.md."
                    ),
                }
            return {
                "ok": True,
                "missing": [],
                "detail": "Z-Image Turbo weights visible to ComfyUI",
            }
    except httpx.ConnectError:
        return {
            "ok": False,
            "missing": [filename for _, filename in ZIMAGE_WEIGHTS.values()],
            "detail": f"Cannot connect to ComfyUI native API at {base}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "missing": [filename for _, filename in ZIMAGE_WEIGHTS.values()],
            "detail": f"ComfyUI weights probe failed: {exc}",
        }


def _attach_weights_probe(health: ServiceHealth, api_url: str) -> ServiceHealth:
    if health.get("status") not in ("ok", "warn"):
        return health
    weights = probe_zimage_weights(resolve_comfyui_native_url(api_url))
    health["weights"] = weights
    if not weights.get("ok"):
        health["status"] = "warn"
        base_detail = health.get("detail") or f"comfyui-api reachable at {api_url}"
        health["detail"] = f"{base_detail}. {weights.get('detail', '')}".strip()
    return health


def probe_comfyui_url(url: str, *, run_probe: bool = True) -> ServiceHealth:
    base = url.rstrip("/")
    if not run_probe:
        return service_health_payload(
            status="skipped",
            url=base,
            detail="Probe skipped",
            latency_ms=None,
        )
    started = time.monotonic()
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            try:
                ready_resp = client.get(f"{base}/ready", timeout=3.0)
                if ready_resp.status_code == 200:
                    latency_ms = int((time.monotonic() - started) * 1000)
                    return _attach_weights_probe(
                        service_health_payload(
                            status="ok",
                            url=base,
                            detail=f"comfyui-api reachable at {base}",
                            latency_ms=latency_ms,
                        ),
                        base,
                    )
            except Exception:  # noqa: BLE001
                pass

            resp = client.get(f"{base}/docs")
            latency_ms = int((time.monotonic() - started) * 1000)
            body_head = resp.text[:512]
            if resp.status_code >= 400 or _is_wrong_app_html(body_head):
                detail = (
                    f"HTTP {resp.status_code} from {base}/docs — "
                    "expected comfyui-api OpenAPI docs, not an HTML page."
                )
                return service_health_payload(
                    status="error",
                    url=base,
                    detail=detail,
                    latency_ms=latency_ms,
                )

            ready_status = "ok"
            ready_detail = f"comfyui-api reachable at {base}"
            try:
                ready_resp = client.get(f"{base}/ready", timeout=3.0)
                if ready_resp.status_code != 200:
                    ready_status = "warn"
                    ready_detail = f"/ready returned HTTP {ready_resp.status_code}"
            except Exception:  # noqa: BLE001
                ready_status = "warn"
                ready_detail = f"comfyui-api reachable at {base} (/ready probe failed)"

            return _attach_weights_probe(
                service_health_payload(
                    status=ready_status,
                    url=base,
                    detail=ready_detail,
                    latency_ms=latency_ms,
                ),
                base,
            )
    except httpx.ConnectError as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return service_health_payload(
            status="error",
            url=base,
            detail=f"Cannot connect to {base}: {exc}. Is comfyui-api running?",
            latency_ms=latency_ms,
        )
    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - started) * 1000)
        return service_health_payload(
            status="error",
            url=base,
            detail=f"Timed out probing {base}/docs",
            latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - started) * 1000)
        return service_health_payload(
            status="error",
            url=base,
            detail=str(exc),
            latency_ms=latency_ms,
        )


def service_health_payload(**fields: Any) -> ServiceHealth:
    out: ServiceHealth = {"id": "comfyui", **fields}
    return out


def comfyui_ready_from_health(result: dict[str, Any]) -> bool:
    return str(result.get("status", "")).lower() in ("ok", "warn")


def discover_comfyui_local(
    settings: dict[str, Any] | None = None,
    *,
    run_probe: bool = True,
    adopt: bool = True,
) -> ServiceHealth:
    """Probe configured URL; scan localhost ports and adopt first valid comfyui-api."""
    configured_url = resolve_configured_comfyui_url(settings)
    candidates_tried: list[str] = [configured_url]

    health = probe_comfyui_url(configured_url, run_probe=run_probe)
    health["configured_url"] = configured_url

    if health.get("status") != "error":
        health["url"] = health.get("url") or configured_url
        return health

    if not run_probe:
        return health

    configured_port = _port_from_url(configured_url)
    for port in discovery_candidate_ports():
        if port == configured_port:
            continue
        candidate_url = f"http://127.0.0.1:{port}"
        if candidate_url in candidates_tried:
            continue
        candidates_tried.append(candidate_url)
        candidate_health = probe_comfyui_url(candidate_url, run_probe=True)
        if candidate_health.get("status") in ("ok", "warn"):
            adopted_url = candidate_url
            if adopt:
                os.environ["COMFYUI_API_URL"] = adopted_url
            log.warning(
                "comfyui discovery adopted %s (configured %s failed: %s)",
                adopted_url,
                configured_url,
                health.get("detail"),
            )
            candidate_health["configured_url"] = configured_url
            candidate_health["adopted_url"] = adopted_url
            candidate_health["candidates_tried"] = candidates_tried
            candidate_health["detail"] = (
                f"Auto-discovered comfyui-api at {adopted_url} "
                f"(configured {configured_url} was unavailable)."
            )
            return candidate_health

    health["candidates_tried"] = candidates_tried
    return health


def _port_from_url(url: str) -> int | None:
    parsed = urlparse(url)
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "http":
        return 80
    if parsed.scheme == "https":
        return 443
    return None


def seed_comfyui_health_cache(settings: dict[str, Any] | None, health: ServiceHealth) -> None:
    """Record a probe result for status polls and /imagine preflight."""
    if health.get("status") not in ("ok", "warn"):
        return
    url = resolve_configured_comfyui_url(settings)
    _health_cache[url] = (time.monotonic(), dict(health))


def get_cached_comfyui_health(
    settings: dict[str, Any] | None = None,
    *,
    run_probe: bool = True,
    operator_id: str | None = None,
    rediscover: bool = False,
) -> ServiceHealth:
    if settings is None:
        from services.settings.store import load_effective_settings

        settings = load_effective_settings(operator_id)
    configured_url = resolve_configured_comfyui_url(settings)
    key = configured_url
    now = time.monotonic()
    cached = _health_cache.get(key)

    if not run_probe:
        if cached:
            return dict(cached[1])
        from services.discovery.registry import get as registry_get

        snap = registry_get("comfyui")
        if snap and str(snap.get("status", "")).lower() in ("ok", "warn", "error"):
            return dict(snap)
        return probe_comfyui_url(configured_url, run_probe=False)

    if not rediscover and cached:
        ts, result = cached
        if now - ts < HEALTH_CACHE_TTL_S and result.get("status") in ("ok", "warn"):
            return dict(result)
    result = discover_comfyui_local(settings, run_probe=True, adopt=True)
    if result.get("status") in ("ok", "warn"):
        _health_cache[key] = (now, dict(result))
    return result


def invalidate_comfyui_health_cache() -> None:
    _health_cache.clear()


def apply_comfyui_url_from_settings(settings: dict[str, Any] | None) -> str:
    url = resolve_configured_comfyui_url(settings)
    os.environ["COMFYUI_API_URL"] = url
    return url


def format_comfyui_unavailable_error(health: dict[str, Any]) -> str:
    url = health.get("url") or health.get("adopted_url") or resolve_configured_comfyui_url()
    detail = health.get("detail") or "ComfyUI is not reachable"
    return (
        f"ComfyUI is not reachable at {url}. {detail} "
        "See Settings → Imagine or infra/comfyui/README.md."
    )


# Backward-compatible alias used by older imports
resolve_comfyui_url = resolve_configured_comfyui_url
