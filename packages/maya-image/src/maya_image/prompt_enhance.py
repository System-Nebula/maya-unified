"""Prompt enhancement for agent-driven image generation."""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


async def enhance_prompt(text: str, *, style: str = "cinematic") -> str:
    """Expand a short scene description into a richer generation prompt."""
    try:
        from maya_image.prompt_builders.ideogram import IdeogramPromptBuilder

        builder = IdeogramPromptBuilder()
        caption = await builder.build(text, path="local")
        if caption:
            return caption
    except Exception as exc:
        logger.debug("enhance_prompt_local_failed", error=str(exc))

    # Lightweight fallback when LLM / Ideogram builder unavailable.
    return f"{text.strip()}, {style}, highly detailed, atmospheric lighting, masterpiece quality"
