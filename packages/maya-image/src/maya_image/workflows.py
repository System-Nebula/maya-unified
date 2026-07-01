"""Workflow registry helpers — resolve image_workflows rows for service/portal/Discord."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from maya_db.sync_connection import get_sync_connection
from maya_db.models.image_workflow import ImageWorkflowRow

logger = structlog.get_logger()

# Discord model choice -> (generate workflow name, edit workflow name)
_MODEL_WORKFLOW_NAMES: dict[str, tuple[str, str | None]] = {
    "ideogram": ("ideogram4-t2i", "ideogram4-remix"),
    "ideogram-local": ("comfyui-ideogram4-t2i", "comfyui-ideogram4-t2i"),
    "comfyui": ("comfyui-ideogram4-t2i", "comfyui-ideogram4-t2i"),
    "zit": ("z-image-turbo-t2i", "z-image-turbo-t2i"),
    "z-image": ("z-image-turbo-t2i", "z-image-turbo-t2i"),
    "krea2": ("krea2-turbo-t2i", "krea2-turbo-t2i"),
    "krea-2": ("krea2-turbo-t2i", "krea2-turbo-t2i"),
    "gpt-image-2": ("gpt-image-2-t2i", "gpt-image-2-edit"),
    "nano-banana-2": ("nano-banana-2-t2i", "nano-banana-2-edit"),
}

# Fallback when no DB row exists (fal models not seeded in migration)
_FALLBACK_PARAMS: dict[str, dict[str, Any]] = {
    "gpt-image-2-t2i": {
        "provider_key": "fal:gpt-image-2",
        "expand_prompt": False,
    },
    "gpt-image-2-edit": {
        "provider_key": "fal:gpt-image-2",
        "expand_prompt": False,
    },
    "nano-banana-2-t2i": {
        "provider_key": "fal:nano-banana-2",
        "expand_prompt": False,
    },
    "nano-banana-2-edit": {
        "provider_key": "fal:nano-banana-2",
        "expand_prompt": False,
    },
}

_SEEDED_SYNTHETIC: dict[str, dict[str, Any]] = {
    "ideogram4-t2i": {
        "id": "a0000001-0000-4000-8000-000000000001",
        "provider": "ideogram",
        "category": "t2i",
        "params": {"provider_key": "ideogram:4", "model_key": "ideogram/4.0", "expand_prompt": True, "magic_prompt_option": "AUTO"},
        # Hosted Ideogram API; the local comfyui-ideogram4-t2i is the arena candidate.
        "is_arena_candidate": False,
    },
    "ideogram4-remix": {
        "id": "a0000001-0000-4000-8000-000000000002",
        "provider": "ideogram",
        "category": "remix",
        "params": {"provider_key": "ideogram:4", "expand_prompt": True},
        "is_arena_candidate": False,
    },
    "comfyui-ideogram4-t2i": {
        "id": "a0000001-0000-4000-8000-000000000003",
        "provider": "comfyui",
        "category": "t2i",
        "display_name": "Ideogram 4 Local",
        "params": {"provider_key": "comfyui:graph", "model_key": "ideogram/4.0", "expand_prompt": True, "aspect": "1:1", "steps": 20, "cfg": 7.0},
        "is_arena_candidate": True,
    },
    "z-image-turbo-t2i": {
        "id": "a0000001-0000-4000-8000-000000000004",
        "provider": "comfyui",
        "category": "t2i",
        "params": {"provider_key": "comfyui:graph", "model_key": "z-image-turbo", "aspect": "9:16", "steps": 8, "cfg": 1.2},
        "is_arena_candidate": True,
    },
    "anima-t2i-turbo": {
        "id": "a0000001-0000-4000-8000-000000000005",
        "provider": "comfyui",
        "category": "t2i",
        "params": {"provider_key": "comfyui:graph", "model_key": "anima-base", "aspect": "16:9", "steps": 12, "cfg": 1.2, "preset": "speed"},
        # Excluded from arena until an HF source for anima-base assets is in the manifest.
        "is_arena_candidate": False,
    },
    "anima-t2i-quality": {
        "id": "a0000001-0000-4000-8000-000000000006",
        "provider": "comfyui",
        "category": "t2i",
        "params": {"provider_key": "comfyui:graph", "model_key": "anima-base", "aspect": "16:9", "steps": 35, "cfg": 4.5, "preset": "quality"},
        # Excluded from arena until an HF source for anima-base assets is in the manifest.
        "is_arena_candidate": False,
    },
    "krea2-turbo-t2i": {
        "id": "a0000001-0000-4000-8000-000000000007",
        "provider": "comfyui",
        "category": "t2i",
        "display_name": "Krea 2 Turbo",
        "params": {"provider_key": "comfyui:graph", "model_key": "krea2-turbo", "aspect": "1:1", "steps": 8, "cfg": 1.0},
        "is_arena_candidate": True,
    },
    "flux2-t2i": {
        "id": "a0000001-0000-4000-8000-000000000008",
        "provider": "comfyui",
        "category": "t2i",
        "display_name": "Flux 2",
        "params": {"provider_key": "comfyui:graph", "model_key": "flux2", "aspect": "1:1", "steps": 20, "cfg": 1.0},
        "is_arena_candidate": True,
    },
}


@dataclass
class ImageWorkflow:
    id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    provider: Optional[str]
    ui_schema: dict[str, Any]
    comfy_graph: Optional[dict[str, Any]]
    params: dict[str, Any]
    elo_score: int = 1200
    total_runs: int = 0
    is_arena_candidate: bool = False
    provider_key: str = ""
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.provider_key:
            self.provider_key = str(self.params.get("provider_key") or "")
        if not self.display_name:
            self.display_name = self.name.replace("-", " ").title()


def _row_to_workflow(row: ImageWorkflowRow) -> ImageWorkflow:
    params = dict(row.params or {})
    return ImageWorkflow(
        id=str(row.id),
        name=row.name,
        description=row.description,
        category=row.category,
        provider=row.provider,
        ui_schema=dict(row.ui_schema or {}),
        comfy_graph=dict(row.comfy_graph) if row.comfy_graph else None,
        params=params,
        elo_score=row.elo_score,
        total_runs=row.total_runs,
        is_arena_candidate=row.is_arena_candidate,
        provider_key=str(params.get("provider_key") or ""),
    )


def _synthetic_workflow(name: str) -> ImageWorkflow:
    seeded = _SEEDED_SYNTHETIC.get(name)
    comfy_graph = None
    ui_schema: dict[str, Any] = {}
    if seeded and seeded.get("provider") == "comfyui":
        from maya_image.comfy_bind import auto_bind
        from maya_image.comfy_graphs import (
            create_anima_t2i_graph,
            create_flux2_graph,
            create_ideogram4_graph,
            create_krea2_turbo_graph,
            create_z_image_turbo_graph,
        )

        if name == "z-image-turbo-t2i":
            comfy_graph = create_z_image_turbo_graph()
        elif name == "krea2-turbo-t2i":
            comfy_graph = create_krea2_turbo_graph()
        elif name == "flux2-t2i":
            comfy_graph = create_flux2_graph()
        elif name == "comfyui-ideogram4-t2i":
            comfy_graph = create_ideogram4_graph()
        elif name == "anima-t2i-turbo":
            comfy_graph = create_anima_t2i_graph(turbo=True)
        elif name == "anima-t2i-quality":
            comfy_graph = create_anima_t2i_graph(turbo=False, steps=35, cfg=4.5)
        if comfy_graph:
            from maya_image.comfy_import import build_ui_schema

            ui_schema = build_ui_schema(auto_bind(comfy_graph))
    if seeded:
        params = dict(seeded.get("params") or {})
        return ImageWorkflow(
            id=str(seeded["id"]),
            name=name,
            description=f"Built-in seed for {name}",
            category=seeded.get("category"),
            provider=seeded.get("provider"),
            ui_schema=ui_schema,
            comfy_graph=comfy_graph,
            params=params,
            provider_key=str(params.get("provider_key") or ""),
            is_arena_candidate=bool(seeded.get("is_arena_candidate")),
            display_name=str(seeded.get("display_name") or ""),
        )
    params = dict(_FALLBACK_PARAMS.get(name, {}))
    provider_key = str(params.get("provider_key", ""))
    provider = provider_key.split(":")[0] if provider_key else "fal"
    category = "remix" if "edit" in name else "t2i"
    return ImageWorkflow(
        id=name,
        name=name,
        description=f"Built-in fallback for {name}",
        category=category,
        provider=provider,
        ui_schema={},
        comfy_graph=None,
        params=params,
        provider_key=provider_key,
        is_arena_candidate=category == "t2i",
    )


def get_workflow(workflow_id: str | uuid.UUID) -> ImageWorkflow:
    """Load a workflow by UUID or by name."""
    name = str(workflow_id)
    if name in _SEEDED_SYNTHETIC or name in _FALLBACK_PARAMS:
        try:
            session = get_sync_connection().get_session()
            try:
                query = session.query(ImageWorkflowRow)
                try:
                    wid = uuid.UUID(name)
                    row = query.filter(ImageWorkflowRow.id == wid).first()
                except ValueError:
                    row = query.filter(ImageWorkflowRow.name == name).first()
                if row is not None:
                    return _row_to_workflow(row)
            finally:
                session.close()
        except Exception as exc:
            logger.debug("workflow_db_lookup_failed", name=name, error=str(exc))
        return _synthetic_workflow(name)

    # Synthetic seed UUID (e.g. a0000001-0000-4000-8000-000000000004) without a DB row.
    for seed_name, seed in _SEEDED_SYNTHETIC.items():
        if str(seed.get("id")) == name:
            return _synthetic_workflow(seed_name)

    session = get_sync_connection().get_session()
    try:
        query = session.query(ImageWorkflowRow)
        try:
            wid = uuid.UUID(str(workflow_id))
            row = query.filter(ImageWorkflowRow.id == wid).first()
        except ValueError:
            row = query.filter(ImageWorkflowRow.name == str(workflow_id)).first()
        if row is None:
            raise ValueError(f"workflow not found: {workflow_id}")
        return _row_to_workflow(row)
    finally:
        session.close()


def _apply_workflow_filters(
    workflows: list[ImageWorkflow],
    *,
    category: str | None,
    provider: str | None,
    is_arena_candidate: bool | None,
) -> list[ImageWorkflow]:
    result = workflows
    if category:
        result = [w for w in result if w.category == category]
    if provider:
        result = [w for w in result if w.provider == provider]
    if is_arena_candidate is not None:
        result = [w for w in result if w.is_arena_candidate == is_arena_candidate]
    return sorted(result, key=lambda w: w.name)


def _merge_db_and_builtin_workflows(db_workflows: list[ImageWorkflow]) -> list[ImageWorkflow]:
    """Merge DB rows with built-in seeds; DB wins on name collision."""
    merged = {name: _synthetic_workflow(name) for name in _SEEDED_SYNTHETIC}
    for wf in db_workflows:
        merged[wf.name] = wf
    return list(merged.values())


def list_workflows(
    *,
    category: str | None = None,
    provider: str | None = None,
    is_arena_candidate: bool | None = None,
) -> list[ImageWorkflow]:
    db_workflows: list[ImageWorkflow] = []
    try:
        session = get_sync_connection().get_session()
        try:
            query = session.query(ImageWorkflowRow)
            if category:
                query = query.filter(ImageWorkflowRow.category == category)
            if provider:
                query = query.filter(ImageWorkflowRow.provider == provider)
            if is_arena_candidate is not None:
                query = query.filter(ImageWorkflowRow.is_arena_candidate == is_arena_candidate)
            rows = query.order_by(ImageWorkflowRow.name).all()
            db_workflows = [_row_to_workflow(r) for r in rows]
        finally:
            session.close()
    except Exception as exc:
        logger.debug("workflow_list_db_failed", error=str(exc))

    merged = _merge_db_and_builtin_workflows(db_workflows)
    return _apply_workflow_filters(
        merged,
        category=category,
        provider=provider,
        is_arena_candidate=is_arena_candidate,
    )


def resolve_workflow_for_model(model_choice: str | None, mode: str = "generate") -> ImageWorkflow:
    """Map a Discord/portal model choice + mode to a workflow row."""
    choice = model_choice or "ideogram"
    names = _MODEL_WORKFLOW_NAMES.get(choice)
    if names is None:
        names = _MODEL_WORKFLOW_NAMES["ideogram"]
    wf_name = names[1] if mode == "edit" and names[1] else names[0]
    try:
        return get_workflow(wf_name)
    except ValueError:
        if wf_name in _FALLBACK_PARAMS:
            return _synthetic_workflow(wf_name)
        logger.warning("workflow_resolve_fallback", model=choice, name=wf_name)
        return get_workflow("ideogram4-t2i")


def resolve_provider_key(workflow: ImageWorkflow, fallback: str = "") -> str:
    """Pick runtime provider key — comfy graphs route to comfyui:graph."""
    if workflow.comfy_graph and workflow.provider == "comfyui":
        return "comfyui:graph"
    return str(workflow.provider_key or workflow.params.get("provider_key") or fallback)


_ARENA_DENIED_WORKFLOW_NAMES = frozenset(
    {"ideogram4-t2i", "ideogram4-remix"}
)

# Local Comfy arena pool (hosted API + stubs excluded via denylist above).
_ARENA_ALLOWED_WORKFLOW_NAMES = frozenset(
    {
        "z-image-turbo-t2i",
        "krea2-turbo-t2i",
        "flux2-t2i",
        "comfyui-ideogram4-t2i",
    }
)


def workflow_is_arena_runnable(workflow: ImageWorkflow) -> bool:
    """Whether a workflow can run in arena without hosted-only or stub endpoints."""
    if not workflow.is_arena_candidate:
        return False
    if workflow.name not in _ARENA_ALLOWED_WORKFLOW_NAMES:
        return False
    if workflow.name in _ARENA_DENIED_WORKFLOW_NAMES:
        return False
    if workflow.params.get("workflow_endpoint"):
        return False
    provider_key = resolve_provider_key(workflow)
    if provider_key == "ideogram:4":
        return False
    if workflow.comfy_graph:
        from maya_image.comfy_assets import assets_ready_for_graph

        return assets_ready_for_graph(workflow.comfy_graph)
    return provider_key.startswith("fal:")


def list_arena_runnable_workflows(
    *,
    category: str | None = None,
    provider: str | None = None,
) -> list[ImageWorkflow]:
    """Arena pool: is_arena_candidate workflows that can run locally or via fal."""
    return [
        w
        for w in list_workflows(category=category, provider=provider, is_arena_candidate=True)
        if workflow_is_arena_runnable(w)
    ]


def workflow_model_label(workflow: ImageWorkflow) -> str:
    """User-facing checkpoint/model label for a workflow."""
    return str(workflow.display_name or workflow.params.get("model_key") or workflow.name)


def workflow_supports_remix(workflow_id: str) -> bool:
    """Whether follow-up remix/edit is wired for this workflow."""
    try:
        wf = get_workflow(workflow_id)
    except ValueError:
        return False
    gen_name = wf.name
    for _choice, (gen, edit) in _MODEL_WORKFLOW_NAMES.items():
        if gen != gen_name:
            continue
        if not edit or edit == gen:
            return False
        return "remix" in edit or "edit" in edit
    return False


def apply_workflow_to_request(workflow: ImageWorkflow, request_metadata: dict[str, Any]) -> dict[str, Any]:
    """Merge workflow default params into job metadata (caller overrides win)."""
    merged = dict(workflow.params)
    merged.update(request_metadata)
    if request_metadata.get("arena_slot") or request_metadata.get("mode") == "arena":
        merged.pop("aspect", None)
    merged["workflow_id"] = workflow.id
    merged.setdefault("provider_key", resolve_provider_key(workflow))
    return merged


def apply_workflow_elo_from_vote(battle_input: dict[str, Any], choice: str, *, delta: int = 16) -> None:
    """Update workflow ELO when a workflow-scoped arena battle receives a vote."""
    contenders = battle_input.get("workflow_contenders") or {}
    wf_a = contenders.get("a")
    wf_b = contenders.get("b")
    if not wf_a or not wf_b or choice not in {"a", "b"}:
        return
    if choice == "a":
        update_workflow_elo(wf_a, won=True, delta=delta)
        update_workflow_elo(wf_b, won=False, delta=delta)
    elif choice == "b":
        update_workflow_elo(wf_b, won=True, delta=delta)
        update_workflow_elo(wf_a, won=False, delta=delta)


def update_workflow_elo(workflow_id: str, *, won: bool, delta: int = 16) -> None:
    """Adjust ELO on image_workflows after an arena vote."""
    try:
        session = get_sync_connection().get_session()
        try:
            query = session.query(ImageWorkflowRow)
            try:
                wid = uuid.UUID(str(workflow_id))
                row = query.filter(ImageWorkflowRow.id == wid).first()
            except ValueError:
                row = query.filter(ImageWorkflowRow.name == str(workflow_id)).first()
            if row is None:
                return
            if won:
                row.elo_score = (row.elo_score or 1200) + delta
            else:
                row.elo_score = max(800, (row.elo_score or 1200) - delta)
            row.total_runs = (row.total_runs or 0) + 1
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        logger.warning("workflow_elo_update_failed", workflow_id=workflow_id, error=str(exc))
