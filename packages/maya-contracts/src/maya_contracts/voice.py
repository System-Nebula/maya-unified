"""Voice control-panel + conversational-pipeline contracts.

These back the drop-in "kitchen-sink" voice SDK (Alpine components) and the
gateway pipeline that turns an operator utterance into Maya's reply:

    listen (detection engine) -> transcript
        -> reasoning model
        -> parsed intent + Maya's conversational turn

``wispr_*`` naming reflects the Wispr-Flow-style dictation defaults we design
around; the implementation here is self-contained (no external dictation
vendor required).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class _VoiceModel(BaseModel):
    """Base for voice contracts.

    Unlike the project-wide ``StrictModel`` (``strict=True``), these are parsed
    leniently so JSON request bodies may pass enum *values* as strings (e.g.
    ``"detection_mode": "vad"``) — which is exactly what the browser SDK sends.
    Strict mode would reject string→enum coercion and 422 the request.
    """

    model_config = ConfigDict(extra="ignore")


class DetectionMode(str, Enum):
    """How the detection engine decides when the operator is speaking."""

    VAD = "vad"  # energy-based voice-activity detection
    PUSH_TO_TALK = "push_to_talk"
    CONTINUOUS = "continuous"  # always-on, no gating


class TurnRole(str, Enum):
    OPERATOR = "operator"
    MAYA = "maya"


class TurnIntent(str, Enum):
    """Coarse intent parsed from the operator transcript."""

    GREETING = "greeting"
    QUESTION = "question"
    COMMAND = "command"
    FAREWELL = "farewell"
    STATEMENT = "statement"
    EMPTY = "empty"


class OperatorVoiceSettings(_VoiceModel):
    """Per-operator defaults for the audio + dictation + reasoning stack.

    Mirrors what a Slack/Discord "Voice & Video" settings pane persists, plus
    the Wispr-Flow-style dictation + reasoning model defaults.
    """

    # --- Audio interface ---
    input_device_id: str | None = None
    output_device_id: str | None = None
    input_gain: float = 1.0
    noise_suppression: bool = True

    # --- Detection engine (pipeline step 1: listen) ---
    detection_mode: DetectionMode = DetectionMode.VAD
    vad_threshold: float = 0.02  # RMS 0..1 above which speech is detected
    vad_hangover_ms: int = 600  # silence to wait before ending a turn
    push_to_talk_key: str = "Space"

    # --- Wispr-Flow-style dictation defaults ---
    wispr_model: str = "wispr-flow-1"
    language: str = "en"
    auto_punctuation: bool = True
    filler_removal: bool = True  # strip "um", "uh", ...

    # --- Reasoning (pipeline step 2) ---
    reasoning_model: str = "maya-reason-mini"
    persona: str = "maya"


class ConversationTurn(_VoiceModel):
    role: TurnRole
    text: str


class VoiceTurnRequest(_VoiceModel):
    """Submit a (transcribed) operator utterance to the conversational pipeline."""

    transcript: str
    settings: OperatorVoiceSettings | None = None
    history: list[ConversationTurn] = Field(default_factory=list)


class VoiceTurnResponse(_VoiceModel):
    """Maya's conversational turn plus a trace of the pipeline steps."""

    transcript_raw: str
    transcript_clean: str
    intent: TurnIntent
    maya_turn: str
    reasoning_model: str
    reasoning_trace: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0


class VoiceDefaultsResponse(_VoiceModel):
    """Catalog + defaults used to populate the settings panel."""

    default_settings: OperatorVoiceSettings
    detection_modes: list[str]
    wispr_models: list[str]
    reasoning_models: list[str]
    languages: list[str]
