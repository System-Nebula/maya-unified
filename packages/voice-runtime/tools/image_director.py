"""Image Director semantic tools for the voice agent."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from .registry import ToolSpec

_IMAGE_TOOL_TIMEOUT = 320.0


def _ctx() -> dict[str, Any]:
    try:
        from services.imagine.director_context import get_image_director_context

        return get_image_director_context()
    except ImportError:
        return {}


def _run_async(coro):
    from services.async_bridge import run_sync

    return run_sync(coro, timeout=_IMAGE_TOOL_TIMEOUT)


def _llm_from_agent():
    try:
        from services.voice.agent_ref import get_agent_llm

        return get_agent_llm()
    except Exception:
        return None


def _settings(operator_id: str | None) -> dict[str, Any]:
    from services.settings.store import load_effective_settings

    return load_effective_settings(operator_id)


def _vision_model(settings: dict[str, Any] | None) -> str:
    from services.imagine.settings import get_imagine_settings

    imagine = get_imagine_settings(settings)
    return str(
        imagine.get("critique_vision_model") or imagine.get("remark_vision_model") or ""
    ).strip()


def _ensure_session(args: dict) -> tuple[str, dict[str, Any]]:
    from maya_image.director.tools import ensure_session

    session_id = args.get("session_id") or _ctx().get("session_id")
    operator_id = args.get("operator_id") or _ctx().get("operator_id")
    sid, state = ensure_session(
        session_id,
        operator_id=operator_id,
        discord_user_id=args.get("discord_user_id"),
        discord_channel_id=args.get("discord_channel_id"),
    )
    try:
        from services.imagine.director_context import set_image_director_context

        set_image_director_context(session_id=sid, operator_id=operator_id)
    except ImportError:
        pass
    return sid, {"operator_id": operator_id, "session_id": sid, "state": state}


def build_image_director_tools(
    *,
    emit: Callable[..., None] | None = None,
    operator_id: str | None = None,
    llm: Any | None = None,
) -> list[ToolSpec]:
    """Register Image Director semantic tools."""

    def _merged_args(args: dict) -> dict:
        merged = dict(args or {})
        ctx = _ctx()
        for key in ("operator_id", "session_id", "corr_id"):
            merged.setdefault(key, ctx.get(key))
        if operator_id:
            merged.setdefault("operator_id", operator_id)
        return merged

    def get_state_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_get_state

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        return _run_async(tool_get_state(sid))

    def parse_intent_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_parse_intent

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        message = str(merged.get("message") or "").strip()
        if not message:
            raise ValueError("message is required")
        agent_llm = llm or _llm_from_agent()
        return _run_async(tool_parse_intent(sid, message, llm=agent_llm, emit=emit))

    def update_goal_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_update_goal

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        delta = merged.get("delta") or merged.get("goal_delta") or {}
        if isinstance(delta, str):
            delta = json.loads(delta)
        return _run_async(tool_update_goal(sid, delta))

    def generate_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_generate

        merged = _merged_args(args)
        sid, info = _ensure_session(merged)
        settings = _settings(merged.get("operator_id"))
        from services.imagine.settings import get_imagine_settings

        imagine = get_imagine_settings(settings)
        metadata = {"model": imagine.get("default_model"), "operator_id": merged.get("operator_id")}
        if emit:
            emit(type="image.director.action", text="Starting a fresh generation from the plan.")
        result = _run_async(
            tool_generate(sid, operator_id=merged.get("operator_id"), metadata=metadata, emit=emit)
        )
        result.setdefault("session_id", sid)
        return result

    def edit_region_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_edit_region

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        settings = _settings(merged.get("operator_id"))
        from services.imagine.settings import get_imagine_settings

        imagine = get_imagine_settings(settings)
        metadata = {"model": imagine.get("default_model")}
        return _run_async(
            tool_edit_region(
                sid,
                mask=str(merged.get("mask") or "subject"),
                denoise=float(merged.get("denoise") or 0.38),
                operator_id=merged.get("operator_id"),
                metadata=metadata,
                emit=emit,
            )
        )

    def edit_style_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_edit_style

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        settings = _settings(merged.get("operator_id"))
        from services.imagine.settings import get_imagine_settings

        imagine = get_imagine_settings(settings)
        metadata = {"model": imagine.get("default_model")}
        return _run_async(
            tool_edit_style(
                sid,
                denoise=float(merged.get("denoise") or 0.45),
                operator_id=merged.get("operator_id"),
                metadata=metadata,
                emit=emit,
            )
        )

    def upscale_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_upscale

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        settings = _settings(merged.get("operator_id"))
        from services.imagine.settings import get_imagine_settings

        imagine = get_imagine_settings(settings)
        metadata = {"model": imagine.get("default_model")}
        return _run_async(
            tool_upscale(
                sid,
                operator_id=merged.get("operator_id"),
                metadata=metadata,
                emit=emit,
            )
        )

    def describe_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_describe

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        settings = _settings(merged.get("operator_id"))
        agent_llm = llm or _llm_from_agent()
        return _run_async(
            tool_describe(sid, llm=agent_llm, vision_model=_vision_model(settings))
        )

    def score_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_score

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        settings = _settings(merged.get("operator_id"))
        from services.imagine.settings import get_imagine_settings

        imagine = get_imagine_settings(settings)
        agent_llm = llm or _llm_from_agent()
        return _run_async(
            tool_score(
                sid,
                llm=agent_llm,
                vision_model=_vision_model(settings),
                multi_critic=bool(imagine.get("director_multi_critic", True)),
                emit=emit,
            )
        )

    def save_version_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_save_version

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        result = _run_async(
            tool_save_version(
                sid,
                operator_id=merged.get("operator_id"),
                action=str(merged.get("action") or "generate"),
            )
        )
        if result.get("ok") and emit:
            state_payload = result.get("state") or {}
            versions = (state_payload.get("versions") or []) if isinstance(state_payload, dict) else []
            emit(
                type="image.director.versions",
                versions=[
                    {"id": v.get("id"), "score": v.get("score"), "parent_id": v.get("parent_id")}
                    for v in versions[-5:]
                ],
            )
        if result.get("ok") and emit and result.get("url"):
            emit(
                type="ai",
                artifacts=[
                    {
                        "type": "image",
                        "url": result.get("url"),
                        "session_id": sid,
                        "version_id": result.get("version_id"),
                        "director": True,
                    }
                ],
            )
        return result

    def restore_version_handler(args: dict) -> dict:
        from maya_image.director.tools import tool_restore_version

        merged = _merged_args(args)
        sid, _ = _ensure_session(merged)
        version_id = str(merged.get("version_id") or "").strip()
        if not version_id:
            raise ValueError("version_id is required")
        return _run_async(tool_restore_version(sid, version_id))

    session_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Existing image director session id"},
            "operator_id": {"type": "string"},
        },
    }

    return [
        ToolSpec(
            name="image_get_state",
            description="Read the structured image goal state for the current director session.",
            parameters={"type": "object", "properties": dict(session_schema["properties"])},
            handler=get_state_handler,
            group="image",
            execution_timeout=_IMAGE_TOOL_TIMEOUT,
        ),
        ToolSpec(
            name="image_parse_intent",
            description=(
                "Parse user natural language into structured image goal deltas. "
                "Never pass raw prompts — mutate goal fields."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **session_schema["properties"],
                    "message": {"type": "string", "description": "User request to interpret"},
                },
                "required": ["message"],
            },
            handler=parse_intent_handler,
            group="image",
            execution_timeout=60.0,
        ),
        ToolSpec(
            name="image_update_goal",
            description="Directly patch structured image goal fields (not a prompt string).",
            parameters={
                "type": "object",
                "properties": {
                    **session_schema["properties"],
                    "delta": {"type": "object", "description": "Nested goal field patch"},
                },
                "required": ["delta"],
            },
            handler=update_goal_handler,
            group="image",
        ),
        ToolSpec(
            name="image_generate",
            description="Generate a new image from the structured goal state (txt2img).",
            parameters={"type": "object", "properties": dict(session_schema["properties"])},
            handler=generate_handler,
            group="image",
            execution_timeout=_IMAGE_TOOL_TIMEOUT,
        ),
        ToolSpec(
            name="image_edit_region",
            description="Inpaint a masked region using the structured goal (not full regeneration).",
            parameters={
                "type": "object",
                "properties": {
                    **session_schema["properties"],
                    "mask": {"type": "string", "description": "Region name e.g. hat, face, background"},
                    "denoise": {"type": "number"},
                },
            },
            handler=edit_region_handler,
            group="image",
            execution_timeout=_IMAGE_TOOL_TIMEOUT,
        ),
        ToolSpec(
            name="image_edit_style",
            description="img2img style or expression edit preserving composition.",
            parameters={
                "type": "object",
                "properties": {
                    **session_schema["properties"],
                    "denoise": {"type": "number"},
                },
            },
            handler=edit_style_handler,
            group="image",
            execution_timeout=_IMAGE_TOOL_TIMEOUT,
        ),
        ToolSpec(
            name="image_upscale",
            description="Upscale the current image with a detail enhancement pass.",
            parameters={"type": "object", "properties": dict(session_schema["properties"])},
            handler=upscale_handler,
            group="image",
            execution_timeout=_IMAGE_TOOL_TIMEOUT,
        ),
        ToolSpec(
            name="image_describe",
            description="Vision-describe the current director session image.",
            parameters={"type": "object", "properties": dict(session_schema["properties"])},
            handler=describe_handler,
            group="image",
            execution_timeout=60.0,
        ),
        ToolSpec(
            name="image_score",
            description=(
                "Run multi-critic vision evaluation against the structured goal. "
                "Returns goal_match, issues, suggested_tool, should_stop."
            ),
            parameters={"type": "object", "properties": dict(session_schema["properties"])},
            handler=score_handler,
            group="image",
            execution_timeout=120.0,
        ),
        ToolSpec(
            name="image_save_version",
            description="Commit the current image to the version tree and present to user.",
            parameters={
                "type": "object",
                "properties": {
                    **session_schema["properties"],
                    "action": {"type": "string"},
                },
            },
            handler=save_version_handler,
            group="image",
            execution_timeout=30.0,
        ),
        ToolSpec(
            name="image_restore_version",
            description="Branch from a historical version in the session version tree.",
            parameters={
                "type": "object",
                "properties": {
                    **session_schema["properties"],
                    "version_id": {"type": "string"},
                },
                "required": ["version_id"],
            },
            handler=restore_version_handler,
            group="image",
        ),
    ]


def image_director_max_rounds() -> int:
    return max(3, int(os.getenv("VA_IMAGE_MAX_ROUNDS", "12")))
