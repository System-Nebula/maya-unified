"""Framework-neutral contracts for typed LLM programs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class LLMProgram(Protocol[InputT, OutputT]):
    async def run(self, request: InputT) -> OutputT: ...


class ToolRoutingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utterance: str
    conversation_id: str | None = None
    execution_id: str | None = None


class ProposedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    group: str = "builtin"
    sequence: int = 1


class ToolRoutingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: Literal["native", "dspy", "ax", "deterministic"]
    final_text: str = ""
    calls: list[ProposedToolCall] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class ProgramArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["maya.llm-program.v1"] = "maya.llm-program.v1"
    artifact_id: str
    framework: Literal["dspy", "ax"]
    framework_version: str
    program_name: str
    base_program_version: str
    artifact_version: str
    optimizer: str
    training_dataset_hash: str
    validation_dataset_hash: str
    git_revision: str
    native_payload: dict[str, Any]
    metrics: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
