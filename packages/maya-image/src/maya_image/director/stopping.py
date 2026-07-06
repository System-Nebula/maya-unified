"""Stopping criteria for the image director refinement loop."""

from __future__ import annotations

from maya_image.director.state import ImageSessionState


def should_stop(state: ImageSessionState, *, score: float | None = None) -> tuple[bool, str]:
    """Return (stop, reason) for the refinement loop."""
    active = state.active_version()
    effective_score = score
    if effective_score is None and active and active.score is not None:
        effective_score = active.score

    if effective_score is not None and effective_score >= 0.90:
        return True, "score_acceptable"

    if state.iteration.count >= state.iteration.max_count:
        return True, "iteration_cap"

    if state.iteration.stall_count >= 2:
        return True, "critic_stall"

    if (
        state.iteration.last_score is not None
        and effective_score is not None
        and state.iteration.count > 0
        and abs(effective_score - state.iteration.last_score) < 0.02
    ):
        return True, "score_plateau"

    return False, ""


def record_iteration(state: ImageSessionState, *, score: float | None, issues: list[str]) -> None:
    """Update iteration counters after a critique pass."""
    if issues and issues == state.iteration.last_issues:
        state.iteration.stall_count += 1
    else:
        state.iteration.stall_count = 0
    state.iteration.last_issues = list(issues)
    if score is not None:
        state.iteration.last_score = score
    state.iteration.count += 1
