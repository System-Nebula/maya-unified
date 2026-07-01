"""Generation mode resolver — "the platform decides".

A generation turn carries a *mode*: a single-workflow response, or a concurrent A/B
"arena" test the platform fans out and surfaces blind for the user to vote on. This
module is the single decision point shared by every surface (web feed, Discord cog) so
the policy lives in one place.

v1 policy: **default to arena**. The decision can be overridden per-request via
``metadata["arena_mode"]`` (``forced_single`` / ``forced_arena`` / ``default``), an
explicit ``ImageMode.ARENA`` on the request, or globally disabled with the
``MAYA_ARENA_DEFAULT`` env var. Reference-driven edits never fan out to a blind A/B in
v1 — they stay single-workflow.

The function is pure and synchronous so it is trivially testable and safe to call from
both async handlers and the Discord cog.
"""

from __future__ import annotations

import os

from maya_image.types.image_job import ImageJobInput, ImageMode

# metadata["arena_mode"] override values
ARENA_MODE_META_KEY = "arena_mode"
FORCED_SINGLE = "forced_single"
FORCED_ARENA = "forced_arena"
DEFAULT = "default"

_DISABLED = {"0", "false", "off", "no"}


def arena_default_enabled() -> bool:
    """Whether the platform defaults a plain generate request to an A/B arena turn."""
    return os.getenv("MAYA_ARENA_DEFAULT", "1").strip().lower() not in _DISABLED


def resolve_generation_mode(request: ImageJobInput) -> ImageMode:
    """Resolve the effective mode for a generation request.

    Returns one of ``ImageMode.EDIT`` (reference-driven), ``ImageMode.GENERATE``
    (single workflow), or ``ImageMode.ARENA`` (concurrent blind A/B).
    """
    # Reference-driven edits are always single-workflow in v1.
    if request.mode == ImageMode.EDIT or request.references:
        return ImageMode.EDIT

    override = (request.metadata or {}).get(ARENA_MODE_META_KEY)
    if override == FORCED_SINGLE:
        return ImageMode.GENERATE
    if override == FORCED_ARENA or request.mode == ImageMode.ARENA:
        return ImageMode.ARENA

    # "default" / unset -> platform policy.
    return ImageMode.ARENA if arena_default_enabled() else ImageMode.GENERATE
