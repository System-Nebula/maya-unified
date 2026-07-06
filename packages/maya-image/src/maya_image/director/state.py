"""Structured image state — the LLM mutates goal fields, not raw prompts."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    PLANNING = "planning"
    GENERATING = "generating"
    CRITIQUING = "critiquing"
    PRESENTING = "presenting"
    DONE = "done"


class HatGoal(BaseModel):
    type: Optional[str] = None
    color: Optional[str] = None


class ImageGoal(BaseModel):
    subject: Optional[str] = None
    expression: Optional[str] = None
    hat: Optional[HatGoal] = None
    style: Optional[str] = None
    composition: Optional[str] = None
    camera: Optional[str] = None
    quality: Optional[str] = None
    background: Optional[str] = None
    extras: dict[str, Any] = Field(default_factory=dict)


class CritiqueRecord(BaseModel):
    critic: str = "merged"
    goal_match: float = 0.0
    issues: list[str] = Field(default_factory=list)
    objects: dict[str, bool] = Field(default_factory=dict)
    fixable_with_edit: bool = False
    suggested_tool: Optional[str] = None
    suggested_mask: Optional[str] = None
    suggested_denoise: Optional[float] = None


class ImageVersion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_id: Optional[str] = None
    image_url: Optional[str] = None
    job_id: Optional[str] = None
    workflow: Optional[str] = None
    seed: Optional[int] = None
    score: Optional[float] = None
    critiques: list[CritiqueRecord] = Field(default_factory=list)
    state_snapshot: Optional[dict[str, Any]] = None
    action: str = "generate"


class IterationState(BaseModel):
    count: int = 0
    max_count: int = 3
    stall_count: int = 0
    last_issues: list[str] = Field(default_factory=list)
    last_score: Optional[float] = None


class ImageSessionState(BaseModel):
    goal: ImageGoal = Field(default_factory=ImageGoal)
    current_version_id: Optional[str] = None
    current_image_url: Optional[str] = None
    current_job_id: Optional[str] = None
    versions: list[ImageVersion] = Field(default_factory=list)
    iteration: IterationState = Field(default_factory=IterationState)
    status: SessionStatus = SessionStatus.PLANNING
    model: Optional[str] = None
    size: str = "1024x1024"
    narration: list[str] = Field(default_factory=list)
    last_critique: Optional[CritiqueRecord] = None

    def active_version(self) -> Optional[ImageVersion]:
        if not self.current_version_id:
            return None
        for v in self.versions:
            if v.id == self.current_version_id:
                return v
        return None

    def apply_delta(self, delta: dict[str, Any]) -> None:
        """Merge a nested goal delta into current state."""
        if not delta:
            return
        goal_data = self.goal.model_dump()
        _deep_merge(goal_data, delta)
        self.goal = ImageGoal.model_validate(goal_data)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
