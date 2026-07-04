"""Shared artifact storage for generated files served by the gateway."""

from services.artifacts.store import artifact_dict_for_path, blender_outputs_root, save_image_bytes

__all__ = ["artifact_dict_for_path", "blender_outputs_root", "save_image_bytes"]
