"""Shared types for service discovery health payloads."""

from __future__ import annotations

from typing import Any, TypedDict


class ServiceHealth(TypedDict, total=False):
    id: str
    status: str
    url: str
    detail: str | None
    latency_ms: int | None
    configured_url: str
    adopted_url: str
    candidates_tried: list[str]
    policy_blocked: bool
    policy_message: str | None
    weights: dict[str, Any]


def service_health(**fields: Any) -> ServiceHealth:
    return fields  # type: ignore[return-value]
