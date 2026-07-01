"""Voice control-panel + conversational-pipeline endpoints.

These back the drop-in voice SDK:

- ``GET  /api/voice/settings/defaults`` — catalog + default operator settings
  used to populate the settings panel (audio, detection engine, Wispr-Flow,
  reasoning model).
- ``POST /api/voice/turn`` — run the reasoning step of the pipeline:
  transcript -> intent -> Maya's conversational turn.

All routes are DB-free and demo-safe.
"""

from __future__ import annotations

from fastapi import APIRouter
from maya_contracts import (
    DetectionMode,
    OperatorVoiceSettings,
    VoiceDefaultsResponse,
    VoiceTurnRequest,
    VoiceTurnResponse,
)

from maya_gateway.services.voice_turn import generate_turn

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.get("/settings/defaults", response_model=VoiceDefaultsResponse)
async def settings_defaults() -> VoiceDefaultsResponse:
    return VoiceDefaultsResponse(
        default_settings=OperatorVoiceSettings(),
        detection_modes=[m.value for m in DetectionMode],
        wispr_models=["wispr-flow-1", "wispr-flow-1-fast", "wispr-flow-pro"],
        reasoning_models=["maya-reason-mini", "maya-reason", "maya-reason-pro"],
        languages=["en", "es", "fr", "de", "ja", "pt"],
    )


@router.post("/turn", response_model=VoiceTurnResponse)
async def voice_turn(req: VoiceTurnRequest) -> VoiceTurnResponse:
    """listen -> reasoning model -> Maya's conversational turn."""
    return generate_turn(req)
