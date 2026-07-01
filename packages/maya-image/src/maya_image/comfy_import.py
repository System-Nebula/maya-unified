"""Import ComfyUI Export-API JSON into image_workflows registry rows."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from maya_image.comfy_bind import auto_bind
from maya_db.sync_connection import get_sync_connection
from maya_db.models.image_workflow import ImageWorkflowRow


DEFAULT_UI_FIELDS = [
    {"name": "prompt", "type": "textarea", "required": True},
    {"name": "aspect", "type": "aspect", "options": ["1:1", "16:9", "9:16"], "default": "16:9"},
    {"name": "preset", "type": "preset", "options": ["speed", "quality"], "default": "speed"},
]


def load_api_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "prompt" in data:
        return data["prompt"]
    if isinstance(data, dict) and "workflow" in data:
        inner = data["workflow"]
        if isinstance(inner, dict):
            return inner
    if isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()):
        return data
    raise ValueError(f"unrecognized Comfy API JSON shape: {path}")


def build_ui_schema(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    return {"fields": list(DEFAULT_UI_FIELDS), "bindings": bindings}


def upsert_workflow_row(
    *,
    name: str,
    comfy_graph: dict[str, Any],
    description: str = "",
    category: str = "t2i",
    provider: str = "comfyui",
    params: Optional[dict[str, Any]] = None,
    bindings: Optional[list[dict[str, Any]]] = None,
    is_arena_candidate: bool = True,
) -> str:
    """Insert or update an image_workflows row. Returns workflow id."""
    bindings = bindings or auto_bind(comfy_graph)
    ui_schema = build_ui_schema(bindings)
    params = params or {
        "provider_key": "comfyui:graph",
        "steps": 12,
        "cfg": 1.2,
        "steps_speed": 12,
        "cfg_speed": 1.2,
        "steps_quality": 35,
        "cfg_quality": 4.5,
        "aspect": "16:9",
        "sampler_name": "euler",
    }
    session = get_sync_connection().get_session()
    try:
        row = session.query(ImageWorkflowRow).filter(ImageWorkflowRow.name == name).first()
        if row is None:
            row = ImageWorkflowRow(
                id=uuid.uuid4(),
                name=name,
                description=description or f"ComfyUI workflow {name}",
                category=category,
                provider=provider,
                ui_schema=ui_schema,
                comfy_graph=comfy_graph,
                params=params,
                is_arena_candidate=is_arena_candidate,
            )
            session.add(row)
        else:
            row.description = description or row.description
            row.category = category
            row.provider = provider
            row.ui_schema = ui_schema
            row.comfy_graph = comfy_graph
            row.params = params
            row.is_arena_candidate = is_arena_candidate
        session.commit()
        return str(row.id)
    finally:
        session.close()


def import_from_file(
    *,
    name: str,
    api_json_path: Path,
    auto_bind_graph: bool = True,
    **kwargs: Any,
) -> str:
    graph = load_api_json(api_json_path)
    bindings = auto_bind(graph) if auto_bind_graph else []
    return upsert_workflow_row(name=name, comfy_graph=graph, bindings=bindings, **kwargs)
