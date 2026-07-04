"""Shared image generation core for /imagine cmd and Discord."""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from services.cmd.models import CmdContext, CmdResult, CmdSurface

if TYPE_CHECKING:
    from maya_image.types.image_job import ImageJobInput
    from maya_image.workflows import ImageWorkflow


def _resolve_mode(raw: str | None):
    from maya_image.types.image_job import ImageMode

    value = (raw or "generate").strip().lower()
    try:
        return ImageMode(value)
    except ValueError:
        return ImageMode.GENERATE


def _cmd_model_default(ctx: CmdContext, model: str | None) -> str | None:
    """Dashboard/chat cmd uses local Comfy Z-Image when model is omitted."""
    if model:
        return str(model)
    if ctx.surface in {CmdSurface.DASHBOARD, CmdSurface.CHAT}:
        return "zit"
    return None


def build_imagine_request(
    *,
    prompt: str,
    operator_id: str | None,
    mode: str = "generate",
    model: str | None = None,
    size: str = "1024x1024",
    quality: str = "high",
    metadata: dict[str, Any] | None = None,
    guild_id: str | None = None,
    channel_id: str | None = None,
    workflow: "ImageWorkflow | None" = None,
) -> tuple[str, "ImageJobInput"]:
    """Build a provider key + ImageJobInput pair for imagine flows."""
    from maya_image.types.image_job import ImageJobInput
    from maya_image.workflows import resolve_workflow_for_model

    image_mode = _resolve_mode(mode)
    wf = workflow or resolve_workflow_for_model(model, mode=image_mode.value)
    provider_key = wf.provider_key or "ideogram:4"
    request = ImageJobInput(
        prompt=prompt,
        mode=image_mode,
        references=[],
        size=size,
        quality=quality,
        user_id=operator_id or "anonymous",
        guild_id=guild_id,
        channel_id=channel_id,
        metadata={
            **(metadata or {}),
            "provider_key": wf.provider_key,
            "workflow_id": wf.id,
            "source": "cmd_registry",
        },
    )
    return provider_key, request


async def run_imagine_job(
    *,
    prompt: str,
    operator_id: str | None,
    mode: str = "generate",
    model: str | None = None,
    size: str = "1024x1024",
    quality: str = "high",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit an image job and wait for completion."""
    from maya_image.service import get_image_service

    if _resolve_mode(mode) != _resolve_mode("generate"):
        raise ValueError("only generate mode is supported via cmd yet")
    provider_key, request = build_imagine_request(
        prompt=prompt,
        operator_id=operator_id,
        mode=mode,
        model=model,
        size=size,
        quality=quality,
        metadata=metadata,
    )
    service = get_image_service()
    job = await service.submit(provider_key, request)
    finished = await service.wait_for_job(
        job.id,
        max_polls=60,
        poll_interval=5.0,
        timeout_sec=300.0,
    )
    output_url = ""
    if finished.output and finished.output.outputs:
        first = finished.output.outputs[0]
        output_url = getattr(first, "url", "") or ""
    return {
        "job_id": finished.id,
        "status": finished.status.value,
        "output_url": output_url,
        "error": finished.error,
        "workflow_id": request.metadata.get("workflow_id"),
        "provider_key": provider_key,
    }


def _trace_id() -> str | None:
    from maya_image.service import current_trace_id

    return current_trace_id()


async def exec_imagine(ctx: CmdContext, args: dict[str, Any]) -> CmdResult:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return CmdResult(ok=False, error="missing required parameter: prompt")
    from services.imagine.settings import get_imagine_settings
    from services.settings.store import load_effective_settings

    settings = load_effective_settings(ctx.operator_id)
    imagine = get_imagine_settings(settings)
    if not imagine.get("enabled"):
        return CmdResult(
            ok=False,
            error="Image generation is disabled in Settings → Imagine.",
        )
    from services.discovery.policy import (
        dev_policy_blocks_imagine,
        dev_policy_message,
        fake_comfy_enabled,
    )
    from services.imagine.health import (
        apply_comfyui_url_from_settings,
        format_comfyui_unavailable_error,
        get_cached_comfyui_health,
    )

    apply_comfyui_url_from_settings(settings)
    health = get_cached_comfyui_health(settings, run_probe=True)
    if health.get("status") == "error":
        health = get_cached_comfyui_health(settings, run_probe=True, rediscover=True)
    if dev_policy_blocks_imagine(health):
        return CmdResult(
            ok=False,
            error=dev_policy_message(),
            trace_id=_trace_id(),
        )
    if health.get("status") == "error" and not fake_comfy_enabled():
        return CmdResult(
            ok=False,
            error=format_comfyui_unavailable_error(health),
            trace_id=_trace_id(),
        )
    mode = str(args.get("mode") or "generate")
    model = _cmd_model_default(ctx, args.get("model"))
    size = str(args.get("size") or "1024x1024")
    quality = str(args.get("quality") or "high")
    try:
        result = await run_imagine_job(
            prompt=prompt,
            operator_id=ctx.operator_id,
            mode=mode,
            model=model,
            size=size,
            quality=quality,
            metadata={"surface": ctx.surface.value},
        )
    except Exception as exc:  # noqa: BLE001
        return CmdResult(ok=False, error=str(exc), trace_id=_trace_id())

    if result.get("status") != "completed":
        job_id = result.get("job_id")
        job_err = result.get("error")
        msg = f"image job {job_id} ended with status {result.get('status')}"
        if job_err:
            msg = f"{msg}: {job_err}"
        return CmdResult(
            ok=False,
            error=msg,
            trace_id=_trace_id(),
            job_id=str(job_id) if job_id else None,
        )
    url = result.get("output_url") or ""
    text = f"Image ready.\nJob: {result.get('job_id')}"
    if url:
        text += f"\n{url}"
    artifacts = [{"type": "image", "url": url, "job_id": result.get("job_id")}] if url else []
    return CmdResult(ok=True, text=text, artifacts=artifacts)


def exec_imagine_sync(ctx: CmdContext, args: dict[str, Any]) -> CmdResult:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(exec_imagine(ctx, args))
    if loop.is_running():
        raise RuntimeError("exec_imagine_sync cannot run inside an active event loop")
    return loop.run_until_complete(exec_imagine(ctx, args))
