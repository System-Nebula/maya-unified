"""Blender MCP helpers for slash commands and services."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from services.artifacts.store import artifact_dict_for_path, blender_outputs_root, save_image_bytes
from services.blender.artifacts import artifact_from_bytes, artifact_from_path
from services.blender.client import BlenderToolResult, call_blender_tool, parse_tool_result

__all__ = [
    "BlenderToolResult",
    "artifact_from_bytes",
    "artifact_from_path",
    "blender_inspect_file",
    "blender_render",
    "blender_run_code",
    "blender_screenshot",
    "blender_summary",
    "call_blender_tool",
    "parse_tool_result",
]


async def blender_summary() -> BlenderToolResult:
    return await call_blender_tool("get_objects_summary")


async def blender_screenshot() -> tuple[BlenderToolResult, list[dict[str, Any]]]:
    result = await call_blender_tool("get_screenshot_of_window_as_image")
    artifacts = [artifact_from_bytes(img) for img in result.images]
    return result, artifacts


async def blender_render() -> tuple[BlenderToolResult, list[dict[str, Any]]]:
    day_dir = blender_outputs_root()
    day_dir.mkdir(parents=True, exist_ok=True)
    output_path = day_dir / f"{uuid.uuid4().hex}.png"
    result = await call_blender_tool(
        "render_viewport_to_path",
        {"output_path": str(output_path)},
    )
    artifacts: list[dict[str, Any]] = []
    if output_path.is_file():
        artifacts.append(artifact_from_path(output_path))
    elif result.images:
        artifacts.extend(artifact_from_bytes(img) for img in result.images)
    return result, artifacts


async def blender_inspect_file(blend_file: str) -> BlenderToolResult:
    path = str(Path(blend_file).expanduser().resolve())
    return await call_blender_tool(
        "get_blendfile_summary_datablocks_for_cli",
        {"blend_file": path},
    )


async def blender_run_code(*, code: str, blend_file: str | None = None) -> tuple[BlenderToolResult, list[dict[str, Any]]]:
    if blend_file:
        path = str(Path(blend_file).expanduser().resolve())
        result = await call_blender_tool(
            "execute_blender_code_for_cli",
            {"blend_file": path, "code": code},
        )
    else:
        result = await call_blender_tool("execute_blender_code", {"code": code})
    artifacts = [artifact_from_bytes(img) for img in result.images]
    return result, artifacts
