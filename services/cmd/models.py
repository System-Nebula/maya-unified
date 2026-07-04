"""cmd_registry data models."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CmdSurface(str, Enum):
    CHAT = "chat"
    DASHBOARD = "dashboard"
    DISCORD = "discord"


CmdExecutor = Callable[["CmdContext", dict[str, Any]], "CmdResult | Awaitable[CmdResult]"]


class CmdParameter(BaseModel):
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None
    choices: list[str] = Field(default_factory=list)


class CmdDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    description: str
    category: str = "Utilities"
    aliases: list[str] = Field(default_factory=list)
    icon: str | None = None
    permissions: list[str] = Field(default_factory=list)
    parameters: list[CmdParameter] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    surfaces: list[CmdSurface] = Field(
        default_factory=lambda: [CmdSurface.CHAT, CmdSurface.DASHBOARD]
    )
    executor: CmdExecutor | None = Field(default=None, exclude=True)

    def discovery_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "aliases": list(self.aliases),
            "icon": self.icon,
            "permissions": list(self.permissions),
            "parameters": [p.model_dump() for p in self.parameters],
            "examples": list(self.examples),
            "tags": list(self.tags),
            "surfaces": [s.value for s in self.surfaces],
        }


class CmdContext(BaseModel):
    operator_id: str | None = None
    surface: CmdSurface = CmdSurface.CHAT
    raw_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedCmd(BaseModel):
    cmd_id: str
    name: str
    raw_args: str = ""
    args: dict[str, Any] = Field(default_factory=dict)


class CmdResult(BaseModel):
    ok: bool
    text: str = ""
    error: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str | None = None
    job_id: str | None = None
    corr_id: str | None = None

    def to_chat_response(self, *, mode: str = "cmd") -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "mode": mode}
        if self.ok:
            out["text"] = self.text
        else:
            out["error"] = self.error or self.text or "command failed"
        if self.artifacts:
            out["artifacts"] = self.artifacts
        if self.events:
            out["events"] = self.events
        if self.trace_id:
            out["trace_id"] = self.trace_id
        if self.job_id:
            out["job_id"] = self.job_id
        if self.corr_id:
            out["corr_id"] = self.corr_id
        return out
