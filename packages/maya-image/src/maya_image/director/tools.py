"""Semantic tool implementations — map to ComfyUI workflows."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

import structlog

from maya_image.director.compile import state_to_edit_prompt, state_to_prompt
from maya_image.director.critique import score_image
from maya_image.director.intent import parse_intent
from maya_image.director.session import (
    create_session,
    get_session_meta,
    load_session,
    save_session,
)
from maya_image.director.state import ImageSessionState, ImageVersion, SessionStatus
from maya_image.director.stopping import record_iteration, should_stop
from maya_image.types.image_job import ImageMode

logger = structlog.get_logger()


def _emit_narration(emit: Callable[..., None] | None, kind: str, text: str = "", **extra: Any) -> None:
    if emit is None:
        return
    try:
        emit(type=f"image.director.{kind}", text=text, **extra)
    except Exception:  # noqa: BLE001
        pass


async def _run_job(
    *,
    session_id: str,
    state: ImageSessionState,
    semantic_tool: str,
    operator_id: str | None,
    metadata: dict[str, Any],
    mask: str | None = None,
    denoise: float | None = None,
    reference_url: str | None = None,
) -> dict[str, Any]:
    from maya_image.service import get_image_service
    from maya_image.workflows import resolve_workflow_for_model
    from services.cmd.executors.imagine import build_imagine_request

    model = state.model or metadata.get("model")
    mode = ImageMode.GENERATE
    if semantic_tool in {"image_edit_region", "image_edit_style"}:
        mode = ImageMode.EDIT
    elif semantic_tool == "image_upscale":
        mode = ImageMode.REFINE

    prompt = state_to_prompt(state.goal)
    if semantic_tool == "image_edit_region" and mask:
        prompt = state_to_edit_prompt(state.goal, region=mask)
    elif semantic_tool == "image_edit_style":
        prompt = state_to_edit_prompt(state.goal)

    job_meta = dict(metadata)
    job_meta["image_session_id"] = session_id
    job_meta["semantic_tool"] = semantic_tool
    if mask:
        job_meta["edit_mask"] = mask
    if denoise is not None:
        job_meta["denoise"] = denoise

    semantic_key = {
        "image_generate": "txt2img",
        "image_edit_region": "inpaint",
        "image_edit_style": "img2img",
        "image_upscale": "upscale",
    }.get(semantic_tool, "txt2img")

    try:
        wf = resolve_workflow_for_model(model, mode=mode.value, semantic=semantic_key)
    except Exception:
        wf = resolve_workflow_for_model(model, mode="generate")

    provider_key, request, wf = build_imagine_request(
        prompt=prompt,
        operator_id=operator_id,
        mode=mode.value,
        model=model,
        size=state.size,
        metadata=job_meta,
        workflow=wf,
    )

    refs = reference_url or state.current_image_url
    if refs and semantic_tool != "image_generate":
        from maya_image.types.image_job import ImageReference

        request = request.model_copy(
            update={
                "references": [ImageReference(source_url=refs)],
                "mode": mode,
            }
        )

    service = get_image_service()
    job = await service.submit(provider_key, request)
    finished = await service.wait_for_job(job.id, max_polls=60, poll_interval=5.0, timeout_sec=300.0)

    output_url = ""
    gen_ms = None
    seed = job_meta.get("seed")
    if finished.output and finished.output.outputs:
        first = finished.output.outputs[0]
        output_url = getattr(first, "url", "") or ""
    if finished.started_at and finished.completed_at:
        gen_ms = int((finished.completed_at - finished.started_at).total_seconds() * 1000)

    state.current_image_url = output_url or state.current_image_url
    state.current_job_id = finished.id
    state.status = SessionStatus.CRITIQUING
    save_session(session_id, state, operator_id=operator_id)

    return {
        "ok": finished.status.value == "completed",
        "job_id": finished.id,
        "url": output_url,
        "status": finished.status.value,
        "error": finished.error,
        "workflow": wf.name,
        "gen_ms": gen_ms,
        "seed": seed,
        "prompt_compiled": prompt,
    }


async def tool_get_state(session_id: str) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    return {"ok": True, "session_id": session_id, "state": state.model_dump(mode="json")}


async def tool_parse_intent(
    session_id: str,
    message: str,
    *,
    llm: Any | None = None,
    emit: Callable[..., None] | None = None,
) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    result = await parse_intent(message, state, llm=llm)
    state.apply_delta(result.get("state_delta") or {})
    state.status = SessionStatus.PLANNING
    save_session(session_id, state)
    _emit_narration(emit, "thinking", text=result.get("rationale") or "Updating the plan.")
    return {"ok": True, "session_id": session_id, **result, "state": state.model_dump(mode="json")}


async def tool_update_goal(session_id: str, delta: dict[str, Any]) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    state.apply_delta(delta or {})
    save_session(session_id, state)
    return {"ok": True, "session_id": session_id, "state": state.model_dump(mode="json")}


async def tool_generate(
    session_id: str,
    *,
    operator_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    emit: Callable[..., None] | None = None,
) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    state.status = SessionStatus.GENERATING
    _emit_narration(emit, "action", text="Starting a fresh generation from the plan.")
    result = await _run_job(
        session_id=session_id,
        state=state,
        semantic_tool="image_generate",
        operator_id=operator_id,
        metadata=dict(metadata or {}),
    )
    if result.get("ok"):
        state.narration.append("Generated a new image from the plan.")
    save_session(session_id, state, operator_id=operator_id)
    return {"ok": result.get("ok", False), "session_id": session_id, **result}


async def tool_edit_region(
    session_id: str,
    *,
    mask: str = "subject",
    denoise: float = 0.38,
    operator_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    emit: Callable[..., None] | None = None,
) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    if not state.current_image_url:
        return {"ok": False, "error": "no image to edit — run image_generate first"}
    state.status = SessionStatus.GENERATING
    _emit_narration(emit, "action", text=f"Trying an inpaint on the {mask}.")
    result = await _run_job(
        session_id=session_id,
        state=state,
        semantic_tool="image_edit_region",
        operator_id=operator_id,
        metadata=dict(metadata or {}),
        mask=mask,
        denoise=denoise,
        reference_url=state.current_image_url,
    )
    save_session(session_id, state, operator_id=operator_id)
    return {"ok": result.get("ok", False), "session_id": session_id, **result}


async def tool_edit_style(
    session_id: str,
    *,
    denoise: float = 0.45,
    operator_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    emit: Callable[..., None] | None = None,
) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    if not state.current_image_url:
        return {"ok": False, "error": "no image to edit"}
    _emit_narration(emit, "action", text="Adjusting style without a full redo.")
    result = await _run_job(
        session_id=session_id,
        state=state,
        semantic_tool="image_edit_style",
        operator_id=operator_id,
        metadata=dict(metadata or {}),
        denoise=denoise,
        reference_url=state.current_image_url,
    )
    save_session(session_id, state, operator_id=operator_id)
    return {"ok": result.get("ok", False), "session_id": session_id, **result}


async def tool_upscale(
    session_id: str,
    *,
    operator_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    emit: Callable[..., None] | None = None,
) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    if not state.current_image_url:
        return {"ok": False, "error": "no image to upscale"}
    _emit_narration(emit, "action", text="One more pass — upscaling.")
    result = await _run_job(
        session_id=session_id,
        state=state,
        semantic_tool="image_upscale",
        operator_id=operator_id,
        metadata=dict(metadata or {}),
        reference_url=state.current_image_url,
    )
    save_session(session_id, state, operator_id=operator_id)
    return {"ok": result.get("ok", False), "session_id": session_id, **result}


async def tool_describe(
    session_id: str,
    *,
    llm: Any | None = None,
    vision_model: str = "",
) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    if not state.current_image_url:
        return {"ok": False, "error": "no image"}
    try:
        from services.imagine.remark import load_image_for_llm

        image_part = load_image_for_llm(state.current_image_url)
        messages = [
            {"role": "system", "content": "Describe this image concisely for an artist agent."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe what you see."},
                    image_part,
                ],
            },
        ]
        resp = await asyncio.to_thread(llm.complete, messages, model=vision_model or None)
        return {"ok": True, "description": (resp.content or "").strip()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


async def tool_score(
    session_id: str,
    *,
    llm: Any | None = None,
    vision_model: str = "",
    multi_critic: bool = True,
    emit: Callable[..., None] | None = None,
) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    if not state.current_image_url:
        return {"ok": False, "error": "no image to score"}
    if llm is None:
        return {"ok": False, "error": "llm required for scoring"}

    critique = await score_image(
        goal=state.goal,
        image_url=state.current_image_url,
        llm=llm,
        vision_model=vision_model,
        multi_critic=multi_critic,
        emit=emit,
    )
    record_iteration(state, score=critique.goal_match, issues=critique.issues)
    state.last_critique = critique
    stop, reason = should_stop(state, score=critique.goal_match)

    for issue in critique.issues[:2]:
        _emit_narration(emit, "thinking", text=issue)

    save_session(session_id, state)
    return {
        "ok": True,
        "session_id": session_id,
        "critique": critique.model_dump(mode="json"),
        "should_stop": stop,
        "stop_reason": reason,
        "suggested_tool": critique.suggested_tool,
        "suggested_mask": critique.suggested_mask,
        "suggested_denoise": critique.suggested_denoise,
        "goal_match": critique.goal_match,
    }


async def tool_save_version(
    session_id: str,
    *,
    operator_id: str | None = None,
    action: str = "generate",
) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    if not state.current_image_url:
        return {"ok": False, "error": "no image to save"}

    parent_id = state.current_version_id
    version = ImageVersion(
        id=str(uuid.uuid4()),
        parent_id=parent_id,
        image_url=state.current_image_url,
        job_id=state.current_job_id,
        action=action,
        state_snapshot=state.goal.model_dump(mode="json"),
    )
    active = state.active_version()
    if active and active.critiques:
        version.critiques = list(active.critiques)
        version.score = active.score
    elif state.last_critique:
        version.critiques = [state.last_critique]
        version.score = state.last_critique.goal_match

    state.versions.append(version)
    state.current_version_id = version.id
    state.status = SessionStatus.PRESENTING
    save_session(session_id, state, operator_id=operator_id)

    try:
        from maya_image.graph import record_image_turn

        meta = get_session_meta(session_id)
        await asyncio.to_thread(
            record_image_turn,
            turn_id=version.id,
            generation_id=version.job_id or version.id,
            provider="comfyui",
            model=state.model or "zit",
            prompt_raw=state_to_prompt(state.goal),
            image_url=version.image_url or "",
            action=action,
            parent_turn_id=parent_id,
            user_id=operator_id or meta.get("discord_user_id"),
            workflow_id=version.workflow,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("save_version_graph_failed", error=str(exc))

    return {
        "ok": True,
        "session_id": session_id,
        "version_id": version.id,
        "url": version.image_url,
        "versions_count": len(state.versions),
        "state": state.model_dump(mode="json"),
    }


async def tool_restore_version(session_id: str, version_id: str) -> dict[str, Any]:
    state = load_session(session_id)
    if state is None:
        return {"ok": False, "error": "session not found"}
    target = next((v for v in state.versions if v.id == version_id), None)
    if target is None:
        return {"ok": False, "error": "version not found"}
    state.current_version_id = target.id
    state.current_image_url = target.image_url
    state.current_job_id = target.job_id
    if target.state_snapshot:
        state.apply_delta({"extras": {}})  # reset path
        from maya_image.director.state import ImageGoal

        state.goal = ImageGoal.model_validate(target.state_snapshot)
    state.status = SessionStatus.PLANNING
    save_session(session_id, state)
    return {
        "ok": True,
        "session_id": session_id,
        "version_id": version_id,
        "url": target.image_url,
        "state": state.model_dump(mode="json"),
    }


def ensure_session(
    session_id: str | None,
    *,
    operator_id: str | None = None,
    discord_user_id: str | None = None,
    discord_channel_id: str | None = None,
) -> tuple[str, ImageSessionState]:
    if session_id:
        state = load_session(session_id)
        if state is not None:
            return session_id, state
    return create_session(
        operator_id=operator_id,
        discord_user_id=discord_user_id,
        discord_channel_id=discord_channel_id,
    )
