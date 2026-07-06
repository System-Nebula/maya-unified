"""Seed Image Director ComfyUI workflows (inpaint, img2img, upscale).

Revision ID: 20260706_director_workflows
Revises: 20260706_image_sessions
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260706_director_workflows"
down_revision: Union[str, None] = "20260706_image_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROOT = Path(__file__).resolve().parents[4] / "infra" / "comfyui" / "workflows"


def _load_graph(rel: str) -> dict:
    return json.loads((_ROOT / rel).read_text())


def _bindings_inpaint() -> list[dict]:
    return [
        {"path": "27.inputs.text", "key": "prompt", "type": "string"},
        {"path": "3.inputs.seed", "key": "seed", "type": "int"},
        {"path": "3.inputs.steps", "key": "steps", "type": "int"},
        {"path": "3.inputs.cfg", "key": "cfg", "type": "float"},
        {"path": "3.inputs.denoise", "key": "denoise", "type": "float"},
    ]


def _bindings_img2img() -> list[dict]:
    return _bindings_inpaint()


def _bindings_upscale() -> list[dict]:
    return [
        {"path": "27.inputs.text", "key": "prompt", "type": "string"},
        {"path": "13.inputs.width", "key": "width", "type": "int"},
        {"path": "13.inputs.height", "key": "height", "type": "int"},
        {"path": "3.inputs.seed", "key": "seed", "type": "int"},
        {"path": "3.inputs.denoise", "key": "denoise", "type": "float"},
    ]


def _sql_json(obj: dict | list) -> str:
    return json.dumps(obj).replace("'", "''")


def upgrade() -> None:
    rows = [
        {
            "id": "b0000001-0000-4000-8000-000000000001",
            "name": "z-image-inpaint",
            "description": "Z-Image Turbo inpaint / regional edit",
            "category": "inpaint",
            "graph": _load_graph("zimage/image_z_image_inpaint.api.json"),
            "bindings": _bindings_inpaint(),
            "params": {
                "provider_key": "comfyui:graph",
                "model_key": "z-image-turbo",
                "steps": 8,
                "cfg": 1.0,
                "denoise": 0.38,
            },
        },
        {
            "id": "b0000001-0000-4000-8000-000000000002",
            "name": "z-image-img2img",
            "description": "Z-Image Turbo img2img style / expression edit",
            "category": "img2img",
            "graph": _load_graph("zimage/image_z_image_img2img.api.json"),
            "bindings": _bindings_img2img(),
            "params": {
                "provider_key": "comfyui:graph",
                "model_key": "z-image-turbo",
                "steps": 8,
                "cfg": 1.0,
                "denoise": 0.45,
            },
        },
        {
            "id": "b0000001-0000-4000-8000-000000000003",
            "name": "latent-upscale",
            "description": "Latent upscale pass for Image Director",
            "category": "upscale",
            "graph": _load_graph("common/latent_upscale.api.json"),
            "bindings": _bindings_upscale(),
            "params": {
                "provider_key": "comfyui:graph",
                "model_key": "z-image-turbo",
                "steps": 6,
                "cfg": 1.0,
                "denoise": 0.25,
            },
        },
    ]
    for row in rows:
        ui = {"bindings": row["bindings"]}
        op.execute(
            f"""
            INSERT INTO image_workflows (
                id, name, description, category, provider,
                ui_schema, comfy_graph, params, is_arena_candidate
            ) VALUES (
                '{row["id"]}',
                '{row["name"]}',
                '{row["description"]}',
                '{row["category"]}',
                'comfyui',
                '{_sql_json(ui)}'::jsonb,
                '{_sql_json(row["graph"])}'::jsonb,
                '{_sql_json(row["params"])}'::jsonb,
                false
            )
            ON CONFLICT (name) DO UPDATE SET
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                ui_schema = EXCLUDED.ui_schema,
                comfy_graph = EXCLUDED.comfy_graph,
                params = EXCLUDED.params
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM image_workflows
        WHERE name IN ('z-image-inpaint', 'z-image-img2img', 'latent-upscale')
        """
    )
