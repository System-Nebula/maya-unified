"""Compile ImageGoal into workflow-specific prompts — internal only."""

from __future__ import annotations

from maya_image.director.state import ImageGoal


def state_to_prompt(goal: ImageGoal) -> str:
    """Build a generation prompt from structured goal fields."""
    parts: list[str] = []
    if goal.subject:
        parts.append(str(goal.subject))
    if goal.expression:
        parts.append(f"{goal.expression} expression")
    if goal.hat:
        hat_bits = []
        if goal.hat.color:
            hat_bits.append(goal.hat.color)
        if goal.hat.type:
            hat_bits.append(goal.hat.type.replace("_", " "))
        if hat_bits:
            parts.append("wearing " + " ".join(hat_bits))
    if goal.style:
        parts.append(f"{goal.style} style")
    if goal.composition:
        parts.append(f"{goal.composition} composition")
    if goal.camera:
        parts.append(f"{goal.camera} camera")
    if goal.quality:
        parts.append(goal.quality)
    if goal.background:
        parts.append(f"background: {goal.background}")
    for key, value in (goal.extras or {}).items():
        if value:
            parts.append(f"{key.replace('_', ' ')}: {value}")
    if not parts:
        return "high quality illustration"
    return ", ".join(parts)


def state_to_edit_prompt(goal: ImageGoal, region: str | None = None) -> str:
    """Prompt for inpaint/img2img focused on a region."""
    base = state_to_prompt(goal)
    if region:
        return f"edit {region}: {base}"
    return base
