"""Agent tool: generate images via ComfyUI (imagine_generate)."""

from __future__ import annotations

import json
from typing import Any

from .registry import ToolSpec

_IMAGINE_TOOL_TIMEOUT = 320.0


def _run_imagine_sync(*, prompt: str, model: str | None, size: str, metadata: dict[str, Any]) -> dict[str, Any]:
    from services.async_bridge import run_sync
    from services.cmd.executors.imagine import run_imagine_job

    return run_sync(
        run_imagine_job(
            prompt=prompt,
            operator_id=metadata.get("operator_id"),
            model=model,
            size=size,
            metadata=metadata,
        ),
        timeout=_IMAGINE_TOOL_TIMEOUT,
    )


def _imagine_generate_handler(args: dict) -> dict[str, Any]:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    model = args.get("model")
    size = str(args.get("size") or "1024x1024")
    operator_id = args.get("operator_id")
    corr_id = args.get("corr_id")

    from services.settings.store import load_effective_settings
    from services.imagine.settings import get_imagine_settings, resolve_imagine_model

    settings = load_effective_settings(operator_id)
    imagine = get_imagine_settings(settings)
    if not imagine.get("enabled"):
        raise ValueError("Image generation is disabled in Settings → Imagine.")
    resolved_model = resolve_imagine_model(model, settings)

    metadata: dict[str, Any] = {
        "surface": "agent_tool",
        "source": "agent_tool",
    }
    if operator_id:
        metadata["portal_user_id"] = operator_id
    if corr_id:
        metadata["corr_id"] = corr_id

    result = _run_imagine_sync(
        prompt=prompt,
        model=resolved_model,
        size=size,
        metadata=metadata,
    )
    if result.get("status") != "completed":
        err = result.get("error") or f"status {result.get('status')}"
        return {"ok": False, "error": err, "job_id": result.get("job_id")}

    return {
        "ok": True,
        "job_id": result.get("job_id"),
        "url": result.get("output_url") or "",
        "prompt": prompt,
        "model": result.get("model_label"),
        "model_key": result.get("model_key"),
        "workflow_id": result.get("workflow_id"),
        "workflow_name": result.get("workflow_name"),
        "gen_ms": result.get("gen_ms"),
    }


def build_imagine_tools(*, operator_id: str | None = None, corr_id: str | None = None) -> list[ToolSpec]:
    """Register imagine_generate for the agent tool loop."""

    def handler(args: dict) -> dict[str, Any]:
        merged = dict(args or {})
        ctx = {}
        try:
            from services.imagine.tool_context import get_imagine_tool_context

            ctx = get_imagine_tool_context()
        except ImportError:
            ctx = {}
        if operator_id and "operator_id" not in merged:
            merged["operator_id"] = operator_id
        if corr_id and "corr_id" not in merged:
            merged["corr_id"] = corr_id
        merged.setdefault("operator_id", ctx.get("operator_id"))
        merged.setdefault("corr_id", ctx.get("corr_id"))
        return _imagine_generate_handler(merged)

    return [
        ToolSpec(
            name="imagine_generate",
            description=(
                "Generate an image from a text prompt using local ComfyUI (Z-Image Turbo, "
                "Krea 2 Turbo, or Ideogram). Use when the user asks to draw, generate, or "
                "create a picture. After it returns, react briefly and wittily to the result."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "What to generate",
                    },
                    "model": {
                        "type": "string",
                        "enum": ["zit", "krea2", "ideogram-local"],
                        "description": "Optional model; defaults to Settings → Imagine default",
                    },
                    "size": {
                        "type": "string",
                        "description": "Optional WxH, default 1024x1024",
                    },
                },
                "required": ["prompt"],
            },
            handler=handler,
            group="imagine",
            execution_timeout=_IMAGINE_TOOL_TIMEOUT,
        ),
    ]


def imagine_tool_result_summary(result: str) -> str:
    """Compact JSON for tool role message when not doing vision finish."""
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return result
    if not isinstance(data, dict):
        return result
    if not data.get("ok"):
        return result
    return json.dumps(
        {
            "ok": True,
            "job_id": data.get("job_id"),
            "url": data.get("url"),
            "model": data.get("model"),
            "prompt": data.get("prompt"),
        },
        ensure_ascii=False,
    )
