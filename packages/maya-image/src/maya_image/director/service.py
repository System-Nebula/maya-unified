"""Image Director orchestration — shared by voice tools and Discord."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import structlog

from maya_image.director.session import find_session_for_discord, load_session, save_session
from maya_image.director.state import SessionStatus
from maya_image.director.tools import (
    ensure_session,
    tool_edit_region,
    tool_generate,
    tool_parse_intent,
    tool_save_version,
    tool_score,
)

logger = structlog.get_logger()


def _resolve_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    from services.imagine.settings import get_imagine_settings

    return get_imagine_settings(settings)


class ImageDirectorService:
    """Runs director turns server-side (Discord) or via individual tools (voice)."""

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm

    async def run_turn(
        self,
        message: str,
        *,
        session_id: str | None = None,
        operator_id: str | None = None,
        discord_user_id: str | None = None,
        discord_channel_id: str | None = None,
        settings: dict[str, Any] | None = None,
        emit: Callable[..., None] | None = None,
        max_iterations: int | None = None,
    ) -> dict[str, Any]:
        """Full director loop: intent → generate → critique → edit → save."""
        session_id, state = ensure_session(
            session_id,
            operator_id=operator_id,
            discord_user_id=discord_user_id,
            discord_channel_id=discord_channel_id,
        )
        imagine = _resolve_settings(settings)
        vision_model = str(
            imagine.get("critique_vision_model") or imagine.get("remark_vision_model") or ""
        ).strip()
        max_iter = max_iterations or int(imagine.get("director_max_iterations") or 3)
        state.iteration.max_count = max_iter

        metadata = {
            "operator_id": operator_id,
            "model": imagine.get("default_model"),
            "surface": "director",
        }

        intent_result = await tool_parse_intent(
            session_id, message, llm=self.llm, emit=emit
        )
        if not intent_result.get("ok"):
            return intent_result

        narration: list[str] = []
        artifact_url = ""
        final_score = 0.0

        suggested = intent_result.get("suggested_next_tool") or "image_generate"
        params = intent_result.get("suggested_params") or {}

        if suggested == "image_restore_version":
            from maya_image.director.tools import tool_restore_version

            vid = params.get("version_id")
            if vid:
                return await tool_restore_version(session_id, str(vid))

        if not state.current_image_url or suggested == "image_generate":
            gen = await tool_generate(
                session_id, operator_id=operator_id, metadata=metadata, emit=emit
            )
            if not gen.get("ok"):
                return {"ok": False, "session_id": session_id, "error": gen.get("error"), "narration": narration}
            artifact_url = gen.get("url") or ""
            narration.append("Generated from the plan.")

        for _ in range(max_iter):
            state = load_session(session_id)
            if state is None:
                break
            score_result = await tool_score(
                session_id,
                llm=self.llm,
                vision_model=vision_model,
                multi_critic=bool(imagine.get("director_multi_critic", True)),
                emit=emit,
            )
            if not score_result.get("ok"):
                break
            final_score = float(score_result.get("goal_match") or 0)
            narration.extend(score_result.get("critique", {}).get("issues", [])[:2])

            if score_result.get("should_stop"):
                break

            tool_name = score_result.get("suggested_tool") or "image_edit_region"
            if tool_name == "image_edit_region":
                edit = await tool_edit_region(
                    session_id,
                    mask=str(score_result.get("suggested_mask") or "subject"),
                    denoise=float(score_result.get("suggested_denoise") or 0.38),
                    operator_id=operator_id,
                    metadata=metadata,
                    emit=emit,
                )
                if edit.get("ok"):
                    artifact_url = edit.get("url") or artifact_url
                    narration.append("Trying an inpaint instead.")
                else:
                    regen = await tool_generate(
                        session_id, operator_id=operator_id, metadata=metadata, emit=emit
                    )
                    if regen.get("ok"):
                        artifact_url = regen.get("url") or artifact_url
            elif tool_name == "image_generate":
                regen = await tool_generate(
                    session_id, operator_id=operator_id, metadata=metadata, emit=emit
                )
                if regen.get("ok"):
                    artifact_url = regen.get("url") or artifact_url

        saved = await tool_save_version(session_id, operator_id=operator_id)
        state = load_session(session_id)
        if state:
            state.status = SessionStatus.DONE
            save_session(session_id, state, operator_id=operator_id)

        await self._maybe_write_memory(session_id, operator_id=operator_id)

        return {
            "ok": True,
            "session_id": session_id,
            "url": saved.get("url") or artifact_url,
            "version_id": saved.get("version_id"),
            "goal_match": final_score,
            "narration": narration,
            "state": state.model_dump(mode="json") if state else {},
        }

    async def _maybe_write_memory(self, session_id: str, *, operator_id: str | None) -> None:
        """Write structured summary to cognitive memory after session completes."""
        state = load_session(session_id)
        if state is None or not operator_id:
            return
        try:
            summary = {
                "character": state.goal.subject,
                "hat": (
                    f"{state.goal.hat.color} {state.goal.hat.type}".strip()
                    if state.goal.hat
                    else None
                ),
                "style": state.goal.style,
                "score": state.active_version().score if state.active_version() else None,
            }
            text = ", ".join(f"{k}={v}" for k, v in summary.items() if v)
            if not text:
                return
            try:
                from memory.cognitive import CognitiveStore  # voice-runtime on path

                store = CognitiveStore(operator_id)
                store.store(f"image session: {text}", tags=["image", "director"])
            except ImportError:
                logger.debug("director_memory_write_skipped", reason="cognitive store unavailable")
        except Exception as exc:  # noqa: BLE001
            logger.debug("director_memory_write_skipped", error=str(exc))

    def resolve_discord_session(
        self,
        *,
        discord_user_id: str,
        discord_channel_id: str,
    ) -> str | None:
        return find_session_for_discord(
            discord_user_id=discord_user_id,
            discord_channel_id=discord_channel_id,
        )


_service: ImageDirectorService | None = None


def get_director_service(llm: Any | None = None) -> ImageDirectorService:
    global _service
    if _service is None:
        _service = ImageDirectorService(llm=llm)
    elif llm is not None:
        _service.llm = llm
    return _service
