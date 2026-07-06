"""Resilient ComfyUI model-asset management.

ComfyUI graphs reference model files (unet/diffusion, text encoders, VAE) by bare
filename. If a file is missing from the local Comfy install, the ``/prompt`` submit
fails opaquely. This module keeps the install honest by:

- deriving the assets a graph needs straight from the graph dict
  (``required_assets_for_graph``), and
- downloading any missing files from Hugging Face on demand
  (``ensure_assets``), using ``HF_TOKEN`` for gated repos.

Downloads use the ``huggingface_hub`` Python API (the ``hf`` CLI is not assumed to
be on PATH). Files land under ``COMFY_MODELS_PATH`` (default ``~/ComfyUI/models``)
in the standard Comfy subdirectory for their type.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()


class MissingComfyAssetError(RuntimeError):
    """Raised when a Comfy graph needs model files that can't be made available."""

    def __init__(self, filenames: list[str], model: str | None = None):
        self.filenames = filenames
        self.model = model
        files = ", ".join(filenames)
        label = f"{model}: " if model else ""
        super().__init__(f"{label}missing model file(s) not installed and unavailable: {files}")


@dataclass(frozen=True)
class Asset:
    """A Comfy model file and where to fetch it from."""

    repo_id: str
    repo_filename: str  # path within the HF repo
    subdir: str  # Comfy models subdir, e.g. "vae", "diffusion_models", "text_encoders"


# Bare filename (as referenced in a Comfy graph) -> source on Hugging Face.
# Covers the four arena models: ZITT, Krea2, Flux2, Ideogram4 (Ideogram4 ships via
# the typed comfyui-ideogram endpoint, so only its local-graph assets appear here).
_MANIFEST: dict[str, Asset] = {
    # ZITT — Comfy-Org/z_image_turbo
    "z_image_turbo_bf16.safetensors": Asset(
        "Comfy-Org/z_image_turbo",
        "split_files/diffusion_models/z_image_turbo_bf16.safetensors",
        "diffusion_models",
    ),
    "qwen_3_4b.safetensors": Asset(
        "Comfy-Org/z_image_turbo",
        "split_files/text_encoders/qwen_3_4b.safetensors",
        "text_encoders",
    ),
    "ae.safetensors": Asset(
        "Comfy-Org/z_image_turbo",
        "split_files/vae/ae.safetensors",
        "vae",
    ),
    # Krea2 — Comfy-Org/Krea-2
    "krea2_turbo_int8_convrot.safetensors": Asset(
        "Comfy-Org/Krea-2",
        "diffusion_models/krea2_turbo_int8_convrot.safetensors",
        "diffusion_models",
    ),
    "qwen3vl_4b_fp8_scaled.safetensors": Asset(
        "Comfy-Org/Krea-2",
        "text_encoders/qwen3vl_4b_fp8_scaled.safetensors",
        "text_encoders",
    ),
    "qwen_image_vae.safetensors": Asset(
        "Comfy-Org/Krea-2",
        "qwen_image_vae.safetensors",
        "vae",
    ),
    # Flux2 — Comfy-Org/flux2-dev (FP8 weights fit a 24GB 3090 Ti)
    "flux2_dev_fp8mixed.safetensors": Asset(
        "Comfy-Org/flux2-dev",
        "split_files/diffusion_models/flux2_dev_fp8mixed.safetensors",
        "diffusion_models",
    ),
    "mistral_3_small_flux2_fp8.safetensors": Asset(
        "Comfy-Org/flux2-dev",
        "split_files/text_encoders/mistral_3_small_flux2_fp8.safetensors",
        "text_encoders",
    ),
    "flux2-vae.safetensors": Asset(
        "Comfy-Org/flux2-dev",
        "split_files/vae/flux2-vae.safetensors",
        "vae",
    ),
    "Flux2TurboComfyv2.safetensors": Asset(
        "Comfy-Org/flux2-dev",
        "split_files/loras/Flux2TurboComfyv2.safetensors",
        "loras",
    ),
    # Ideogram 4 — Comfy-Org/Ideogram-4
    "ideogram4_fp8_scaled.safetensors": Asset(
        "Comfy-Org/Ideogram-4",
        "ideogram4_fp8_scaled.safetensors",
        "diffusion_models",
    ),
    "ideogram4_unconditional_fp8_scaled.safetensors": Asset(
        "Comfy-Org/Ideogram-4",
        "ideogram4_unconditional_fp8_scaled.safetensors",
        "diffusion_models",
    ),
    "qwen3vl_8b_fp8_scaled.safetensors": Asset(
        "Comfy-Org/Ideogram-4",
        "qwen3vl_8b_fp8_scaled.safetensors",
        "text_encoders",
    ),
}

# Loader-node input keys whose value is a model filename we may need to fetch.
_MODEL_NAME_KEYS = {
    "ckpt_name",
    "unet_name",
    "vae_name",
    "clip_name",
    "clip_name1",
    "clip_name2",
    "model_name",
    "lora_name",
    "gguf_name",
}

_MODEL_FILE_SUFFIXES = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin")


def models_root() -> Path:
    """Root of the local ComfyUI ``models`` directory (host side of the bind mount)."""
    return Path(os.path.expanduser(os.getenv("COMFY_MODELS_PATH", "~/ComfyUI/models")))


def _comfy_container() -> str:
    """Name of the Comfy docker container, used when the models dir is root-owned.

    Comfy typically runs in a container that bind-mounts the models dir as root, so a
    host-side process cannot write it directly. ``docker cp`` writes through the daemon.
    Set ``COMFY_CONTAINER=""`` to disable the docker fallback (bare-metal installs).
    """
    return os.getenv("COMFY_CONTAINER", "comfyui-api-dev")


def _container_models_root() -> str:
    return os.getenv("COMFY_CONTAINER_MODELS_PATH", "/opt/ComfyUI/models")


def resolve_hf_token() -> str | None:
    return os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")


def _place_file(cached: str, asset: "Asset", target: Path) -> None:
    """Place a downloaded file into the Comfy models dir.

    Tries a direct host copy; if the dir is root-owned (dockerized Comfy), falls back
    to ``docker cp`` into the container, which writes through to the bind-mounted host
    dir. The HF cache path is a symlink into ``blobs/`` so it is dereferenced first.
    """
    real = os.path.realpath(cached)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(real, target)
        return
    except PermissionError:
        pass

    container = _comfy_container()
    if not container:
        raise PermissionError(f"cannot write {target} and no COMFY_CONTAINER configured")
    dest = f"{container}:{_container_models_root()}/{asset.subdir}/{target.name}"
    subprocess.run(["docker", "cp", real, dest], check=True, capture_output=True, text=True)


def _target_path(filename: str) -> Path | None:
    asset = _MANIFEST.get(filename)
    if asset is None:
        return None
    return models_root() / asset.subdir / filename


def _already_present(filename: str) -> bool:
    """True if the file already exists in any known Comfy models subdir."""
    asset = _MANIFEST.get(filename)
    root = models_root()
    if asset is not None and (root / asset.subdir / filename).is_file():
        return True
    # Fall back to scanning the common subdirs (handles manual installs / unknowns).
    for sub in ("diffusion_models", "unet", "text_encoders", "clip", "vae", "checkpoints", "loras"):
        if (root / sub / filename).is_file():
            return True
    return False


def required_assets_for_graph(graph: dict | None) -> list[str]:
    """Collect model filenames referenced by loader nodes in a Comfy API graph."""
    found: list[str] = []
    if not isinstance(graph, dict):
        return found
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if key not in _MODEL_NAME_KEYS:
                continue
            if isinstance(value, str) and value.lower().endswith(_MODEL_FILE_SUFFIXES):
                if value not in found:
                    found.append(value)
    return found


def missing_assets(filenames: list[str]) -> list[str]:
    """Return filenames not present locally (check only, no download)."""
    return [name for name in filenames if not _already_present(name)]


def assets_ready_for_graph(graph: dict | None) -> bool:
    """True when every model file referenced by the graph exists locally."""
    needed = required_assets_for_graph(graph)
    if not needed:
        return True
    return not missing_assets(needed)


def ensure_assets(filenames: list[str]) -> list[str]:
    """Ensure each file is present locally, downloading from HF if needed.

    Returns the list of filenames that are still missing afterward (unknown source
    or failed download) so callers can surface a clear, actionable error.
    """
    missing: list[str] = []
    for filename in filenames:
        if _already_present(filename):
            continue
        asset = _MANIFEST.get(filename)
        if asset is None:
            logger.warning("comfy_asset_unknown", filename=filename)
            missing.append(filename)
            continue
        target = models_root() / asset.subdir / filename
        try:
            from huggingface_hub import hf_hub_download

            logger.info(
                "comfy_asset_downloading",
                filename=filename,
                repo_id=asset.repo_id,
                target=str(target),
            )
            cached = hf_hub_download(
                repo_id=asset.repo_id,
                filename=asset.repo_filename,
                token=resolve_hf_token(),
            )
            _place_file(cached, asset, target)
            logger.info("comfy_asset_ready", filename=filename, target=str(target))
        except Exception as exc:  # noqa: BLE001 — resilient: report, don't crash submit
            logger.error(
                "comfy_asset_failed",
                filename=filename,
                repo_id=asset.repo_id,
                error=str(exc),
            )
            missing.append(filename)
    return missing


def ensure_assets_for_graph(graph: dict | None) -> list[str]:
    """Convenience: derive required assets from a graph and ensure them."""
    return ensure_assets(required_assets_for_graph(graph))
