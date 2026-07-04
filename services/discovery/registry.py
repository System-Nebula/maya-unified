"""In-process registry of external service health snapshots."""

from __future__ import annotations

import logging
from typing import Any, Callable

from services.discovery.comfyui import (
    discover_comfyui_local,
    invalidate_comfyui_health_cache,
    seed_comfyui_health_cache,
)
from services.discovery.models import ServiceHealth
from services.discovery.policy import apply_dev_policy

log = logging.getLogger("maya-unified.discovery.registry")

ServiceProbe = Callable[[dict[str, Any] | None], ServiceHealth]

_snapshot: dict[str, ServiceHealth] = {}
_probes: dict[str, ServiceProbe] = {
    "comfyui": lambda settings: discover_comfyui_local(settings, run_probe=True, adopt=True),
}


def register_probe(service_id: str, probe: ServiceProbe) -> None:
    _probes[service_id] = probe


def probe_service(service_id: str, settings: dict[str, Any] | None = None) -> ServiceHealth:
    probe = _probes.get(service_id)
    if probe is None:
        return {"id": service_id, "status": "error", "detail": f"unknown service: {service_id}"}
    health = probe(settings)
    health["id"] = service_id
    _snapshot[service_id] = health
    if service_id == "comfyui":
        seed_comfyui_health_cache(settings, health)
    return health


def probe_all(settings: dict[str, Any] | None = None) -> dict[str, ServiceHealth]:
    results: dict[str, ServiceHealth] = {}
    for service_id in _probes:
        results[service_id] = probe_service(service_id, settings)
    apply_dev_policy(results)
    log.info(
        "service discovery complete comfyui=%s url=%s",
        results.get("comfyui", {}).get("status"),
        results.get("comfyui", {}).get("url"),
    )
    return results


def get(service_id: str) -> ServiceHealth | None:
    return _snapshot.get(service_id)


def snapshot() -> dict[str, ServiceHealth]:
    return dict(_snapshot)


def refresh_comfyui(settings: dict[str, Any] | None = None) -> ServiceHealth:
    invalidate_comfyui_health_cache()
    return probe_service("comfyui", settings)
