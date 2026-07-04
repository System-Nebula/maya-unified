"""Save Blender MCP image results as dashboard artifacts."""

from __future__ import annotations

from pathlib import Path

from services.artifacts.store import artifact_dict_for_path, save_image_bytes

__all__ = ["artifact_from_bytes", "artifact_from_path"]


def artifact_from_bytes(data: bytes, *, suffix: str = ".png") -> dict:
    path = save_image_bytes(data, suffix=suffix)
    return artifact_dict_for_path(path)


def artifact_from_path(path: Path | str) -> dict:
    return artifact_dict_for_path(path)
