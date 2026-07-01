"""Upsert local Comfy arena workflows (z-image, krea2, flux2).

Revision ID: 20260628_seed_workflows
Revises: 20260627_image_jobs
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260628_seed_workflows"
down_revision: Union[str, None] = "20260627_image_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "arena_workflows_seed.json"


def _sql_json(obj: dict) -> str:
    return json.dumps(obj).replace("'", "''")


def upgrade() -> None:
    rows = json.loads(_SEED_PATH.read_text())
    values = []
    for row in rows:
        values.append(
            "("
            f"'{row['id']}', "
            f"'{row['name']}', "
            f"'{row['description']}', "
            "'t2i', 'comfyui', "
            f"'{_sql_json(row['ui'])}'::jsonb, "
            f"'{_sql_json(row['graph'])}'::jsonb, "
            f"'{_sql_json(row['params'])}'::jsonb, "
            f"{'true' if row['arena'] else 'false'}"
            ")"
        )
    op.execute(
        f"""
        INSERT INTO image_workflows (id, name, description, category, provider, ui_schema, comfy_graph, params, is_arena_candidate)
        VALUES {', '.join(values)}
        ON CONFLICT (name) DO UPDATE SET
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            provider = EXCLUDED.provider,
            ui_schema = EXCLUDED.ui_schema,
            comfy_graph = EXCLUDED.comfy_graph,
            params = EXCLUDED.params,
            is_arena_candidate = EXCLUDED.is_arena_candidate
        """
    )
    op.execute(
        """
        UPDATE image_workflows
        SET is_arena_candidate = false
        WHERE name IN ('comfyui-ideogram4-t2i', 'flux2-t2i')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM image_workflows
        WHERE name IN ('z-image-turbo-t2i', 'krea2-turbo-t2i', 'flux2-t2i')
        """
    )
