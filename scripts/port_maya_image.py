#!/usr/bin/env python3
"""Port lib/image + lib/arena from private Workspace into packages/maya-image."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

PRIVATE = Path.home() / "Workspace"
PUBLIC = Path(__file__).resolve().parents[1]
DEST_ROOT = PUBLIC / "packages" / "maya-image" / "src" / "maya_image"

IMAGE_FILES = [
    "__init__.py",
    "arena_layout.py",
    "arena_pair.py",
    "base.py",
    "comfy_assets.py",
    "comfy_bind.py",
    "comfy_graphs.py",
    "comfy_import.py",
    "graph.py",
    "mode_resolver.py",
    "prompt_enhance.py",
    "service.py",
    "storage.py",
    "workflows.py",
    "providers/__init__.py",
    "providers/comfyui_graph.py",
    "providers/comfyui_ideogram.py",
    "providers/comfyui_dispatch.py",
    "providers/comfyui_job_registry.py",
    "providers/comfyui_webhook.py",
    "providers/fake_comfy.py",
    "providers/ideogram.py",
    "providers/ideogram_api.py",
    "providers/fal_base.py",
    "providers/fal_ideogram.py",
    "providers/fal_gpt_image2.py",
    "providers/fal_nano_banana2.py",
    "providers/hunyuan.py",
    "providers/luma.py",
    "providers/kling.py",
    "providers/hidream.py",
    "providers/wan.py",
    "providers/qwen.py",
    "prompt_builders/__init__.py",
    "prompt_builders/ideogram.py",
]

ARENA_FILES = [
    "__init__.py",
    "service.py",
]

REWRITES = [
    (r"\bfrom lib\.image\.", "from maya_image."),
    (r"\bimport lib\.image\.", "import maya_image."),
    (r"\bfrom lib\.arena\.", "from maya_image.arena."),
    (r"\bfrom lib\.db\.arena import", "from maya_db.models.arena import"),
    (r"\bfrom lib\.db\.connection import", "from maya_db.sync_connection import"),
    (r"\bget_connection\b", "get_sync_connection"),
    (r"\bfrom lib\.db\.image_job import", "from maya_db.models.image_job import"),
    (r"\bfrom lib\.db\.models\.image_workflow import", "from maya_db.models.image_workflow import"),
    (r"\bfrom lib\.types\.image_job import", "from maya_image.types.image_job import"),
    (r"\bfrom lib\.db\.age import get_age", "from maya_image.graph_age import get_age"),
    (r"\bfrom lib\.arena\.elo import", "from arena_core.elo import"),
]


def rewrite(content: str) -> str:
    for pattern, repl in REWRITES:
        content = re.sub(pattern, repl, content)
    return content


def port_file(rel: str, *, subdir: str = "") -> None:
    src = PRIVATE / "lib" / "image" / rel
    if subdir:
        dest = DEST_ROOT / subdir / Path(rel).name
    else:
        dest = DEST_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text()
    dest.write_text(rewrite(text))


def main() -> None:
    if DEST_ROOT.exists():
        shutil.rmtree(DEST_ROOT)
    DEST_ROOT.mkdir(parents=True)

    for rel in IMAGE_FILES:
        port_file(rel)

    (DEST_ROOT / "arena").mkdir(exist_ok=True)
    for rel in ARENA_FILES:
        src = PRIVATE / "lib" / "arena" / rel
        dest = DEST_ROOT / "arena" / rel
        dest.write_text(rewrite(src.read_text()))

    types_dir = DEST_ROOT / "types"
    types_dir.mkdir(exist_ok=True)
    (types_dir / "__init__.py").write_text('"""Image job types."""\n')
    (types_dir / "image_job.py").write_text(
        (PRIVATE / "lib" / "types" / "image_job.py").read_text()
    )

    auth_dir = DEST_ROOT / "auth"
    auth_dir.mkdir(exist_ok=True)
    (auth_dir / "__init__.py").write_text("")
    (auth_dir / "identity.py").write_text(
        '''"""Minimal auth stubs for self-hosted bot (portal link optional)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PortalUser:
    id: str


async def resolve_discord_user_standalone(discord_user_id: str) -> PortalUser | None:
    return None
'''
    )

    portal_dir = DEST_ROOT / "portal"
    portal_dir.mkdir(exist_ok=True)
    (portal_dir / "__init__.py").write_text("")
    (portal_dir / "activity.py").write_text(
        '''"""Activity event stubs (optional gateway integration)."""

from __future__ import annotations


async def emit_event_standalone(*_args, **_kwargs) -> None:
    return None
'''
    )

    (DEST_ROOT / "graph_age.py").write_text(
        '''"""Optional Apache AGE graph — best-effort no-op in public build."""

from __future__ import annotations


class _AgeStub:
    def execute(self, *_args, **_kwargs):
        return None


def get_age():
    return _AgeStub()


def record_image_turn(*_args, **_kwargs) -> None:
    return None


def update_turn_rating(*_args, **_kwargs) -> None:
    return None
'''
    )

    graph_py = DEST_ROOT / "graph.py"
    graph_py.write_text(
        graph_py.read_text().replace(
            "from maya_image.graph_age import get_age",
            "from maya_image.graph_age import get_age, record_image_turn, update_turn_rating",
        )
    )

    print(f"Ported maya_image to {DEST_ROOT}")


if __name__ == "__main__":
    main()
