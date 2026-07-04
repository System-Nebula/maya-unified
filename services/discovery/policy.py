"""Dev dependency policy for external services."""

from __future__ import annotations

import logging
import os
from typing import Any

from services.discovery.comfyui import comfyui_ready_from_health
from services.imagine.settings import get_imagine_settings

log = logging.getLogger("maya-unified.discovery.policy")

DEV_POLICY_MESSAGE = (
    "Dev policy requires a local comfyui-api. "
    "Start infra/comfyui or set MAYA_FAKE_COMFY=1 for GPU-free smoke."
)

_imagine_ready: bool = True
_policy_message: str | None = None


def is_dev() -> bool:
    return (
        os.getenv("ENV", "production") == "development"
        or os.getenv("ENVIRONMENT", "development") == "development"
    )


def fake_comfy_enabled() -> bool:
    return os.getenv("MAYA_FAKE_COMFY", "").strip().lower() in {"1", "true", "yes", "on"}


def comfy_satisfies_dev_policy(health: dict[str, Any]) -> bool:
    if fake_comfy_enabled():
        return True
    return comfyui_ready_from_health(health)


def imagine_ready_for_env(health: dict[str, Any], *, settings: dict[str, Any] | None = None) -> bool:
    if settings is not None and not get_imagine_settings(settings).get("enabled"):
        return False
    if is_dev():
        return comfy_satisfies_dev_policy(health)
    return comfyui_ready_from_health(health) or fake_comfy_enabled()


def apply_dev_policy(services_health: dict[str, Any]) -> None:
    """Record dev policy outcome after startup discovery."""
    global _imagine_ready, _policy_message
    comfy = services_health.get("comfyui") or {}
    if is_dev() and not comfy_satisfies_dev_policy(comfy):
        _imagine_ready = False
        _policy_message = DEV_POLICY_MESSAGE
        log.warning("dev policy: imagine unavailable — %s", DEV_POLICY_MESSAGE)
    else:
        _imagine_ready = comfy_satisfies_dev_policy(comfy) if is_dev() else True
        _policy_message = None


def imagine_capability_ready(
    health: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
) -> bool:
    if settings is not None and not get_imagine_settings(settings).get("enabled"):
        return False
    if is_dev():
        if fake_comfy_enabled():
            return True
        if not comfy_satisfies_dev_policy(health):
            return False
    return comfyui_ready_from_health(health) or fake_comfy_enabled()


def dev_policy_blocks_imagine(health: dict[str, Any]) -> bool:
    if not is_dev():
        return False
    if fake_comfy_enabled():
        return False
    return not comfy_satisfies_dev_policy(health)


def dev_policy_message() -> str:
    return _policy_message or DEV_POLICY_MESSAGE


def startup_imagine_ready() -> bool:
    return _imagine_ready
