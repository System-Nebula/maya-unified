"""Image workflow registry for /imagine and arena pairing.

Revision ID: 20260626_image_workflows
Revises: 20260625_arena_superset
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260626_image_workflows"
down_revision: Union[str, None] = "20260625_arena_superset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UI_T2I = """{
  "fields": [
    {"name": "prompt", "type": "textarea", "required": true},
    {"name": "aspect", "type": "aspect", "options": ["1:1", "16:9", "9:16"], "default": "1:1"},
    {"name": "magic_prompt", "type": "toggle", "default": true, "label": "Magic prompt"}
  ]
}"""

_PARAMS_COMFYUI_T2I = """{
  "provider_key": "comfyui:graph",
  "workflow_endpoint": "ideogram4-t2i",
  "aspect": "1:1",
  "expand_prompt": true
}"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS image_workflows (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL UNIQUE,
            description TEXT,
            category VARCHAR(50),
            provider VARCHAR(50),
            ui_schema JSONB NOT NULL DEFAULT '{}',
            comfy_graph JSONB,
            params JSONB NOT NULL DEFAULT '{}',
            elo_score INTEGER DEFAULT 1200,
            total_runs INTEGER DEFAULT 0,
            is_arena_candidate BOOLEAN DEFAULT false,
            arena_competitor_id UUID REFERENCES image_workflows(id),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_image_workflows_comfy_graph "
        "ON image_workflows USING GIN (comfy_graph)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_image_workflows_category ON image_workflows (category)"
    )
    op.execute(
        f"""
        INSERT INTO image_workflows (id, name, description, category, provider, ui_schema, params, is_arena_candidate)
        VALUES (
            'a0000001-0000-4000-8000-000000000003',
            'comfyui-ideogram4-t2i',
            'Local ComfyUI Ideogram 4.0 text-to-image',
            't2i',
            'comfyui',
            '{_UI_T2I}'::jsonb,
            '{_PARAMS_COMFYUI_T2I}'::jsonb,
            false
        )
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS image_workflows")
