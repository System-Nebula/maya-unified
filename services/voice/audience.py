"""Immutable event audience tags (VOICE-002 / SEC-004)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AudienceKind(str, Enum):
    GLOBAL = "global"
    OPERATOR = "operator"
    ROOM = "room"


@dataclass(frozen=True)
class Audience:
    """Exact delivery audience — capture at turn start, never re-infer later."""

    kind: AudienceKind
    id: str | None = None

    def __post_init__(self) -> None:
        if self.kind is AudienceKind.GLOBAL and self.id is not None:
            raise ValueError("global audience must not have an id")
        if self.kind is AudienceKind.OPERATOR and not self.id:
            raise ValueError("operator audience requires an id")
        if self.kind is AudienceKind.ROOM and not self.id:
            raise ValueError("room audience requires an id")

    def to_dict(self) -> dict[str, str | None]:
        return {"kind": self.kind.value, "id": self.id}

    @classmethod
    def from_dict(cls, raw: object) -> Audience | None:
        if not isinstance(raw, dict):
            return None
        kind_raw = str(raw.get("kind") or "").strip().lower()
        try:
            kind = AudienceKind(kind_raw)
        except ValueError:
            return None
        aid = raw.get("id")
        aid_s = str(aid).strip() if aid is not None and str(aid).strip() else None
        try:
            return cls(kind=kind, id=aid_s)
        except ValueError:
            return None

    @classmethod
    def global_(cls) -> Audience:
        return cls(kind=AudienceKind.GLOBAL, id=None)

    @classmethod
    def operator(cls, operator_id: str) -> Audience:
        return cls(kind=AudienceKind.OPERATOR, id=str(operator_id))

    @classmethod
    def room(cls, room_id: str) -> Audience:
        return cls(kind=AudienceKind.ROOM, id=str(room_id))


def audience_matches(subscriber: Audience, event: Audience) -> bool:
    """Exact match; global events reach every subscriber."""
    if event.kind is AudienceKind.GLOBAL:
        return True
    return subscriber == event


def subscriber_audience(
    *,
    operator_id: str | None = None,
    room_id: str | None = None,
) -> Audience | None:
    """Map an SSE subscription to an exact audience (room wins over operator)."""
    if room_id:
        return Audience.room(str(room_id))
    if operator_id:
        return Audience.operator(str(operator_id))
    return None


def should_deliver(subscriber: Audience | None, event: Audience) -> bool:
    """Unscoped subscribers receive only global events."""
    if event.kind is AudienceKind.GLOBAL:
        return True
    if subscriber is None:
        return False
    return audience_matches(subscriber, event)


# Event types that may be delivered without an explicit operator/room audience.
GLOBAL_EVENT_TYPES = frozenset({"ready"})

# Private surfaces — never treat a missing audience as global (SEC-004).
PRIVATE_EVENT_TYPES = frozenset(
    {
        "audio",
        "audio_begin",
        "audio_stop",
        "audio_queued",
        "clear_audio",
        "lip",
        "user",
        "ai",
        "assistant",
        "settings",
        "status",
        "error",
        "delivery",
        "expression",
        "avatar_expression",
        "tool_start",
        "tool_end",
        "tool_trace",
        "tts_info",
        "tts_error",
        "tts_reload",
        "tts_degraded",
        "stt_degraded",
        "stt_ready",
        "barge_in",
        "playback_started",
        "playback_progress",
        "playback_ended",
        "orchestrator",
        "queue_granted",
        "queue_released",
        "audio_degraded",
        "webllm_request",
        "webllm_unload",
    }
)


def resolve_broadcast_audience(
    event: dict,
    *,
    operator_id: str | None = None,
    room_id: str | None = None,
) -> Audience | None:
    """Resolve the immutable delivery audience for a broadcast.

    Prefer ``event['audience']``. Else build from kwargs / legacy fields.
    Private types without an audience return None (caller must drop).
    Allowlisted global types may default to ``Audience.global_()``.
    """
    raw = event.get("audience")
    if raw is not None:
        return Audience.from_dict(raw)

    ev_op = str(operator_id or event.get("operator_id") or "").strip() or None
    ev_room = str(room_id or event.get("room_id") or "").strip() or None
    if ev_op and ev_room:
        return None
    if ev_room:
        return Audience.room(ev_room)
    if ev_op:
        return Audience.operator(ev_op)

    etype = str(event.get("type") or "")
    if etype in GLOBAL_EVENT_TYPES:
        return Audience.global_()
    return None
