"""Programmatic ComfyUI API graphs for registry seed workflows."""

from __future__ import annotations

import random
from typing import Any, Optional


# Fixed prompt for parity-contract / polyglot generation smoke (Comfy template style).
ZIMAGE_PARITY_PROMPT = (
    "Latina female with thick wavy hair, harbor boats and pastel houses behind. "
    "Breezy seaside light, warm tones, cinematic close-up."
)


def create_z_image_turbo_graph(
    *,
    width: int = 1024,
    height: int = 1024,
    steps: int = 8,
    cfg: float = 1.0,
    seed: Optional[int] = None,
    prompt: str = ZIMAGE_PARITY_PROMPT,
    filename_prefix: str = "zimage_polyglot",
    aura_shift: float = 3.0,
) -> dict[str, Any]:
    """Z-Image Turbo t2i graph (API format).

    Node IDs match ``workflows/zimage/image_z_image_turbo.api.json`` and the
    official Comfy template topology (ModelSamplingAuraFlow + res_multistep).
    """
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    return {
        "28": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "z_image_turbo_bf16.safetensors",
                "weight_dtype": "default",
            },
        },
        "11": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["28", 0], "shift": aura_shift},
        },
        "30": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen_3_4b.safetensors",
                "type": "lumina2",
                "device": "default",
            },
        },
        "29": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "27": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["30", 0]},
        },
        "33": {
            "class_type": "ConditioningZeroOut",
            "inputs": {"conditioning": ["27", 0]},
        },
        "13": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "res_multistep",
                "scheduler": "simple",
                "denoise": 1,
                "model": ["11", 0],
                "positive": ["27", 0],
                "negative": ["33", 0],
                "latent_image": ["13", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["29", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": filename_prefix},
        },
    }


def create_anima_t2i_graph(
    *,
    width: int = 1152,
    height: int = 648,
    steps: int = 12,
    cfg: float = 1.2,
    seed: Optional[int] = None,
    prompt: str = "best quality, masterpiece, anime style",
    turbo: bool = True,
) -> dict[str, Any]:
    """Anima t2i graph template (API format). Turbo preset uses fewer steps."""
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    if turbo:
        steps = min(steps, 12)
        cfg = min(cfg, 1.5)
    return {
        "10": {
            "inputs": {"filename_prefix": "Anima", "images": ["8", 0]},
            "class_type": "SaveImage",
        },
        "1": {
            "inputs": {"unet_name": "anima-base-v1.0.safetensors", "weight_dtype": "default"},
            "class_type": "UNETLoader",
        },
        "2": {
            "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "qwen_image", "device": "default"},
            "class_type": "CLIPLoader",
        },
        "3": {"inputs": {"vae_name": "qwen_image_vae.safetensors"}, "class_type": "VAELoader"},
        "4": {
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptySD3LatentImage",
        },
        "5": {
            "inputs": {"text": prompt, "clip": ["2", 0]},
            "class_type": "CLIPTextEncode",
        },
        "6": {"inputs": {"conditioning": ["5", 0]}, "class_type": "ConditioningZeroOut"},
        "7": {
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["1", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["4", 0],
            },
            "class_type": "KSampler",
        },
        "8": {"inputs": {"samples": ["7", 0], "vae": ["3", 0]}, "class_type": "VAEDecode"},
    }


def create_flux2_graph(
    *,
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 1.0,
    guidance: float = 4.0,
    seed: Optional[int] = None,
    prompt: str = "best quality, masterpiece",
) -> dict[str, Any]:
    """FLUX.2-dev (FP8) t2i graph (API format), tuned for a 24GB RTX 3090 Ti.

    Mirrors Comfy-Org's ``image_flux2_fp8`` reference: FP8 diffusion weights, the
    Mistral-3-small flux2 text encoder, the small flux2 VAE decoder, and the Flux2
    Turbo LoRA for few-step sampling. Uses a standard ``KSampler`` (with FluxGuidance
    on the positive conditioning, cfg 1.0) so the registry's auto-bound steps/cfg/seed
    inject cleanly, like the z-image and krea2 graphs.
    """
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    return {
        "1": {
            "inputs": {"unet_name": "flux2_dev_fp8mixed.safetensors", "weight_dtype": "default"},
            "class_type": "UNETLoader",
        },
        "2": {
            "inputs": {
                "model": ["1", 0],
                "lora_name": "Flux2TurboComfyv2.safetensors",
                "strength_model": 1.0,
            },
            "class_type": "LoraLoaderModelOnly",
        },
        "3": {
            "inputs": {
                "clip_name": "mistral_3_small_flux2_fp8.safetensors",
                "type": "flux2",
                "device": "default",
            },
            "class_type": "CLIPLoader",
        },
        "4": {"inputs": {"vae_name": "flux2-vae.safetensors"}, "class_type": "VAELoader"},
        "5": {
            "inputs": {"text": prompt, "clip": ["3", 0]},
            "class_type": "CLIPTextEncode",
        },
        "6": {
            "inputs": {"conditioning": ["5", 0], "guidance": guidance},
            "class_type": "FluxGuidance",
        },
        "7": {"inputs": {"conditioning": ["5", 0]}, "class_type": "ConditioningZeroOut"},
        "8": {
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptyFlux2LatentImage",
        },
        "9": {
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["2", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["8", 0],
            },
            "class_type": "KSampler",
        },
        "10": {"inputs": {"samples": ["9", 0], "vae": ["4", 0]}, "class_type": "VAEDecode"},
        "11": {
            "inputs": {"images": ["10", 0], "filename_prefix": "Flux2"},
            "class_type": "SaveImage",
        },
    }


def create_krea2_turbo_graph(
    *,
    width: int = 1024,
    height: int = 1024,
    steps: int = 8,
    cfg: float = 1.0,
    seed: Optional[int] = None,
    prompt: str = "best quality, masterpiece",
) -> dict[str, Any]:
    """Krea 2 Turbo FP8 t2i graph (API format)."""
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    return {
        "1": {
            "inputs": {"unet_name": "krea2_turbo_int8_convrot.safetensors", "weight_dtype": "default"},
            "class_type": "UNETLoader",
        },
        "2": {
            "inputs": {"clip_name": "qwen3vl_4b_fp8_scaled.safetensors", "type": "krea2", "device": "default"},
            "class_type": "CLIPLoader",
        },
        "3": {"inputs": {"vae_name": "qwen_image_vae.safetensors"}, "class_type": "VAELoader"},
        "4": {
            "inputs": {"text": prompt, "clip": ["2", 0]},
            "class_type": "CLIPTextEncode",
        },
        "5": {"inputs": {"conditioning": ["4", 0]}, "class_type": "ConditioningZeroOut"},
        "6": {
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptyLatentImage",
        },
        "7": {
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
            },
            "class_type": "KSampler",
        },
        "8": {"inputs": {"samples": ["7", 0], "vae": ["3", 0]}, "class_type": "VAEDecode"},
        "9": {
            "inputs": {"images": ["8", 0], "filename_prefix": "krea2_turbo"},
            "class_type": "SaveImage",
        },
    }


def _repo_workflow_path(rel: str):
    """Locate a workflow template by walking up from this file to the repo root."""
    from pathlib import Path

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / rel
        if candidate.is_file():
            return candidate
    return here.parents[2] / rel


_IDEOGRAM4_API_GRAPH = _repo_workflow_path(
    "infra/comfyui/workflows/ideogram4/image_ideogram4_t2i.api.json"
)


def create_ideogram4_graph(
    *,
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    seed: Optional[int] = None,
    prompt: str = "best quality, masterpiece",
) -> dict[str, Any]:
    """Ideogram 4 local t2i graph (API format) from the committed comfyui workflow template."""
    import copy
    import json

    from maya_image.comfy_bind import build_ideogram_caption

    raw = json.loads(_IDEOGRAM4_API_GRAPH.read_text())
    graph: dict[str, Any] = {}
    for node_id, node in raw.items():
        cleaned = {k: v for k, v in node.items() if k != "_meta"}
        graph[node_id] = cleaned
    if seed is None:
        seed = random.randint(0, 2**32 - 1)
    graph["5"]["inputs"]["text"] = build_ideogram_caption(prompt)
    graph["8"]["inputs"]["width"] = width
    graph["8"]["inputs"]["height"] = height
    graph["8"]["inputs"]["steps"] = steps
    graph["10"]["inputs"]["noise_seed"] = seed
    graph["11"]["inputs"]["width"] = width
    graph["11"]["inputs"]["height"] = height
    return graph
