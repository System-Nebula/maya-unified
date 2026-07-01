"""Inject runtime values into ComfyUI API-format workflow graphs.

Replaces Megumin-style manual ``%prompt%`` / ``%width%`` editing with declarative
bindings stored in ``image_workflows.ui_schema.bindings``.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
from typing import Any, Optional

from maya_image.types.image_job import ImageJobInput, ImageMode


def is_arena_request(request: ImageJobInput) -> bool:
    """True when generating an A/B arena slot (shared resolution required)."""
    meta = request.metadata or {}
    return (
        request.mode == ImageMode.ARENA
        or bool(meta.get("arena_slot"))
        or meta.get("mode") == ImageMode.ARENA.value
    )


def normalize_arena_resolution(request: ImageJobInput) -> ImageJobInput:
    """Lock both arena slots to one shared width×height (fair blind comparison)."""
    env_size = os.getenv("MAYA_ARENA_SIZE", "").strip()
    size = env_size or request.size or "1024x1024"
    width, height = _parse_size(size)
    size_str = f"{width}x{height}"
    meta = dict(request.metadata or {})
    meta.pop("aspect", None)
    meta["mode"] = ImageMode.ARENA.value
    meta["arena_width"] = width
    meta["arena_height"] = height
    return request.model_copy(
        update={"size": size_str, "mode": ImageMode.ARENA, "metadata": meta},
    )


def build_ideogram_caption(prompt: str) -> str:
    """Wrap a plain prompt in the structured JSON caption Ideogram 4 expects.

    A bare sentence lands off-distribution and trips Ideogram 4's internal safety
    placeholder; the model is trained on this JSON caption shape. Pass-through if the
    prompt already looks like JSON.
    """
    s = (prompt or "").strip()
    if s.startswith("{") and s.endswith("}"):
        return s
    return json.dumps(
        {
            "high_level_description": prompt,
            "style_description": {
                "aesthetics": "detailed, polished",
                "lighting": "natural, balanced",
                "art_style": "high-quality digital illustration",
                "medium": "illustration",
            },
            "compositional_deconstruction": {
                "background": "a fitting scene for the subject",
                "elements": [{"type": "obj", "desc": prompt}],
            },
        }
    )


_TRANSFORMS = {"ideogram_caption": build_ideogram_caption}


def _parse_size(size: str) -> tuple[int, int]:
    if "x" in size.lower():
        parts = size.lower().split("x", 1)
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    if ":" in size:
        parts = size.split(":", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            w, h = int(parts[0]), int(parts[1])
            base = 1024
            if w >= h:
                return base, int(base * h / w)
            return int(base * w / h), base
    return 1024, 1024


def set_path(graph: dict[str, Any], path: str, value: Any) -> None:
    """Set a dotted path like ``5.inputs.width`` on a Comfy API graph."""
    parts = path.split(".")
    if len(parts) < 2:
        raise ValueError(f"invalid binding path: {path}")
    node_id, *rest = parts
    if node_id not in graph:
        raise KeyError(f"node {node_id} not in graph")
    cur: dict[str, Any] = graph[node_id]
    for key in rest[:-1]:
        cur = cur[key]
    cur[rest[-1]] = value


def inject(
    comfy_graph: dict[str, Any],
    bindings: list[dict[str, Any]],
    values: dict[str, Any],
) -> dict[str, Any]:
    """Deep-copy graph and apply explicit bindings."""
    graph = copy.deepcopy(comfy_graph)
    for binding in bindings:
        key = binding.get("key")
        path = binding.get("path")
        if not key or not path:
            continue
        if key not in values or values[key] is None:
            continue
        value = values[key]
        btype = binding.get("type", "string")
        if btype == "int":
            value = int(value)
        elif btype == "float":
            value = float(value)
        transform = binding.get("transform")
        if transform and transform in _TRANSFORMS:
            value = _TRANSFORMS[transform](value)
        set_path(graph, path, value)
    return graph


def auto_bind(comfy_graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Scan a Comfy API graph and infer common injectable bindings."""
    bindings: list[dict[str, Any]] = []
    positive_nodes: list[str] = []
    sampler_nodes: list[str] = []
    latent_nodes: list[str] = []

    for node_id, node in comfy_graph.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        inputs = node.get("inputs") or {}
        if class_type in {"CLIPTextEncode", "TextEncodeQwenImage", "TextEncode"}:
            text = str(inputs.get("text", "")).lower()
            if any(w in text for w in ("bad", "blurry", "worst", "negative")):
                continue
            positive_nodes.append(node_id)
        elif class_type in {"KSampler", "SamplerCustomAdvanced"}:
            sampler_nodes.append(node_id)
        elif class_type in {
            "EmptyLatentImage",
            "EmptySD3LatentImage",
            "EmptyFlux2LatentImage",
        }:
            latent_nodes.append(node_id)
        elif class_type == "Ideogram4Scheduler" and "width" in inputs and "height" in inputs:
            bindings.extend(
                [
                    {"path": f"{node_id}.inputs.width", "key": "width", "type": "int"},
                    {"path": f"{node_id}.inputs.height", "key": "height", "type": "int"},
                ]
            )
        elif class_type == "RandomNoise":
            bindings.append({"path": f"{node_id}.inputs.noise_seed", "key": "seed", "type": "int"})

    if positive_nodes:
        bindings.append(
            {"path": f"{positive_nodes[0]}.inputs.text", "key": "prompt", "type": "string"}
        )
    if sampler_nodes:
        sid = sampler_nodes[0]
        bindings.extend(
            [
                {"path": f"{sid}.inputs.steps", "key": "steps", "type": "int"},
                {"path": f"{sid}.inputs.cfg", "key": "cfg", "type": "float"},
                {"path": f"{sid}.inputs.seed", "key": "seed", "type": "int"},
                {"path": f"{sid}.inputs.sampler_name", "key": "sampler_name", "type": "string"},
            ]
        )
    for lid in latent_nodes:
        bindings.extend(
            [
                {"path": f"{lid}.inputs.width", "key": "width", "type": "int"},
                {"path": f"{lid}.inputs.height", "key": "height", "type": "int"},
            ]
        )
    return bindings


def build_values_from_request(
    request: ImageJobInput,
    *,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Map ImageJobInput + workflow params to binding value keys."""
    meta = request.metadata or {}
    p = dict(params or {})
    if is_arena_request(request):
        aw, ah = meta.get("arena_width"), meta.get("arena_height")
        if aw is not None and ah is not None:
            width, height = int(aw), int(ah)
        else:
            width, height = _parse_size(request.size)
    else:
        width, height = _parse_size(request.size)
        aspect = meta.get("aspect") or p.get("aspect")
        if aspect and isinstance(aspect, str) and ":" in aspect and "x" not in aspect:
            width, height = _parse_size(aspect)

    preset = meta.get("preset") or p.get("preset")
    steps = meta.get("steps") or p.get("steps")
    cfg = meta.get("cfg") or p.get("cfg")
    if preset == "speed":
        steps = p.get("steps_speed", steps or 12)
        cfg = p.get("cfg_speed", cfg or 1.2)
    elif preset == "quality":
        steps = p.get("steps_quality", steps or 35)
        cfg = p.get("cfg_quality", cfg or 4.5)

    seed = meta.get("seed")
    if seed is None:
        seed = secrets.randbelow(2**32)

    return {
        "prompt": request.prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg": cfg,
        "seed": seed,
        "sampler_name": meta.get("sampler_name") or p.get("sampler_name"),
    }


def inject_request(
    comfy_graph: dict[str, Any],
    bindings: list[dict[str, Any]],
    request: ImageJobInput,
    *,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Convenience: build values from request and inject into graph."""
    merged_bindings = list(bindings or [])
    if is_arena_request(request):
        auto = auto_bind(comfy_graph)
        seen = {(b.get("path"), b.get("key")) for b in merged_bindings}
        for binding in auto:
            if binding.get("key") in {"width", "height"}:
                key = (binding.get("path"), binding.get("key"))
                if key not in seen:
                    merged_bindings.append(binding)
                    seen.add(key)
    if not merged_bindings:
        merged_bindings = auto_bind(comfy_graph)
    values = build_values_from_request(request, params=params)
    return inject(comfy_graph, merged_bindings, values)
