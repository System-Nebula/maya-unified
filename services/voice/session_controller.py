"""Atomic voice session ownership and lifecycle (VOICE-001)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from services.ids import new_session_id
from services.voice.audience import Audience, AudienceKind


class SessionPhase(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True)
class ActiveSession:
    session_id: str
    generation_id: int
    owner: Audience
    mic_source: str
    cancel: threading.Event
    phase: SessionPhase
    connection_id: str | None = None
    principal_id: str | None = None
    principal_name: str | None = None


@dataclass
class VoiceSessionController:
    """Compare-and-swap session ownership. Never run I/O under ``_lock``."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _active: ActiveSession | None = None
    _generation: int = 0

    def snapshot(self) -> ActiveSession | None:
        """Return an immutable point-in-time record (never the mutable controller)."""
        with self._lock:
            return self._active

    @staticmethod
    def _owner_payload(cur: ActiveSession) -> dict[str, Any]:
        payload: dict[str, Any] = cur.owner.to_dict()
        payload["principal_id"] = cur.principal_id
        payload["principal_name"] = cur.principal_name
        return payload

    def is_current(self, session_id: str, generation_id: int) -> bool:
        with self._lock:
            cur = self._active
            return (
                cur is not None
                and cur.session_id == session_id
                and cur.generation_id == generation_id
                and cur.phase
                not in (SessionPhase.STOPPING, SessionPhase.IDLE, SessionPhase.ERROR)
            )

    def connection_is_current(
        self,
        session_id: str,
        generation_id: int,
        connection_id: str,
    ) -> bool:
        with self._lock:
            cur = self._active
            return (
                cur is not None
                and cur.session_id == session_id
                and cur.generation_id == generation_id
                and cur.connection_id == connection_id
                and cur.phase
                not in (SessionPhase.STOPPING, SessionPhase.IDLE, SessionPhase.ERROR)
            )

    def begin_start(
        self,
        owner: Audience,
        *,
        mic_source: str = "browser",
        principal_id: str | None = None,
        principal_name: str | None = None,
    ) -> dict[str, Any]:
        """Allocate STARTING session or return idempotent/conflict.

        Caller must run workers **outside** the lock, then ``complete_start``.
        """
        if owner.kind is AudienceKind.GLOBAL:
            return {"ok": False, "error": "owner_required"}
        principal = str(principal_id or owner.id or "").strip() or None
        principal_name = str(principal_name or "").strip() or None
        with self._lock:
            cur = self._active
            if cur is not None:
                if cur.phase is SessionPhase.STOPPING:
                    return {
                        "ok": False,
                        "error": "stopping",
                        "session_id": cur.session_id,
                    }
                if cur.owner == owner and cur.principal_id == principal and cur.phase in (
                    SessionPhase.STARTING,
                    SessionPhase.LISTENING,
                    SessionPhase.TRANSCRIBING,
                    SessionPhase.THINKING,
                    SessionPhase.SPEAKING,
                ):
                    return {
                        "ok": True,
                        "idempotent": True,
                        "session_id": cur.session_id,
                        "generation_id": cur.generation_id,
                        "phase": cur.phase.value,
                        "mic_source": cur.mic_source,
                    }
                return {
                    "ok": False,
                    "error": "conflict",
                    "owner": self._owner_payload(cur),
                    "session_id": cur.session_id,
                }
            self._generation += 1
            cancel = threading.Event()
            session = ActiveSession(
                session_id=new_session_id(),
                generation_id=self._generation,
                owner=owner,
                mic_source=mic_source,
                cancel=cancel,
                phase=SessionPhase.STARTING,
                principal_id=principal,
                principal_name=principal_name,
            )
            self._active = session
            return {
                "ok": True,
                "idempotent": False,
                "session_id": session.session_id,
                "generation_id": session.generation_id,
                "phase": session.phase.value,
                "mic_source": session.mic_source,
                "cancel": cancel,
            }

    def complete_start(
        self,
        session_id: str,
        generation_id: int,
        *,
        ok: bool,
    ) -> dict[str, Any]:
        """Publish LISTENING if still current; compare-and-clear on failure."""
        with self._lock:
            cur = self._active
            if (
                cur is None
                or cur.session_id != session_id
                or cur.generation_id != generation_id
            ):
                try:
                    from services.voice.metrics import record_stale_generation_drop

                    record_stale_generation_drop(
                        meta={"generation_id": int(generation_id)}
                    )
                except Exception:
                    pass
                return {"ok": False, "error": "stale"}
            if not ok:
                if cur.phase is SessionPhase.STARTING:
                    self._active = None
                return {"ok": False, "error": "start_failed"}
            if cur.phase is SessionPhase.STARTING:
                cur = replace(cur, phase=SessionPhase.LISTENING)
                self._active = cur
            return {
                "ok": True,
                "session_id": cur.session_id,
                "generation_id": cur.generation_id,
                "phase": cur.phase.value,
            }

    def begin_stop(
        self,
        requester: Audience | None,
        *,
        admin: bool = False,
        principal_id: str | None = None,
    ) -> dict[str, Any]:
        """Mark STOPPING and invalidate generation. Tear down outside the lock."""
        with self._lock:
            cur = self._active
            if cur is None:
                return {"ok": True, "idle": True}
            if not admin:
                if requester is None:
                    return {"ok": False, "error": "forbidden"}
                principal = str(principal_id or requester.id or "").strip() or None
                if cur.owner != requester or cur.principal_id != principal:
                    return {
                        "ok": False,
                        "error": "forbidden",
                        "owner": self._owner_payload(cur),
                        "session_id": cur.session_id,
                    }
            if cur.phase is SessionPhase.STOPPING:
                return {
                    "ok": True,
                    "already_stopping": True,
                    "session_id": cur.session_id,
                    "generation_id": cur.generation_id,
                    "cancel": cur.cancel,
                }
            self._generation += 1
            cur.cancel.set()
            cur = replace(
                cur,
                phase=SessionPhase.STOPPING,
                generation_id=self._generation,
            )
            self._active = cur
            return {
                "ok": True,
                "session_id": cur.session_id,
                "generation_id": cur.generation_id,
                "cancel": cur.cancel,
                "owner": self._owner_payload(cur),
            }

    def complete_stop(
        self,
        session_id: str,
        generation_id: int | None = None,
    ) -> dict[str, Any]:
        """Clear active state only if the exact stopped lifecycle still matches."""
        with self._lock:
            cur = self._active
            if cur is None:
                return {"ok": True, "cleared": False}
            if cur.session_id != session_id or (
                generation_id is not None and cur.generation_id != generation_id
            ):
                return {"ok": False, "error": "stale", "cleared": False}
            self._active = None
            return {"ok": True, "cleared": True}

    def set_phase(
        self,
        session_id: str,
        generation_id: int,
        phase: SessionPhase,
    ) -> bool:
        with self._lock:
            cur = self._active
            if (
                cur is None
                or cur.session_id != session_id
                or cur.generation_id != generation_id
            ):
                return False
            if cur.phase is SessionPhase.STOPPING:
                return False
            self._active = replace(cur, phase=phase)
            return True

    def bind_connection(
        self,
        session_id: str,
        generation_id: int,
        connection_id: str,
    ) -> bool:
        """Bind the one current browser socket by exact lifecycle token."""
        with self._lock:
            cur = self._active
            if (
                cur is None
                or cur.session_id != session_id
                or cur.generation_id != generation_id
                or cur.phase in (SessionPhase.STOPPING, SessionPhase.ERROR)
            ):
                return False
            self._active = replace(cur, connection_id=str(connection_id))
            return True

    def clear_connection(
        self,
        session_id: str,
        generation_id: int,
        connection_id: str,
    ) -> bool:
        """Compare-and-clear; an old socket can never detach its replacement."""
        with self._lock:
            cur = self._active
            if (
                cur is None
                or cur.session_id != session_id
                or cur.generation_id != generation_id
                or cur.connection_id != connection_id
            ):
                return False
            self._active = replace(cur, connection_id=None)
            return True

    def set_connection_id(self, session_id: str, connection_id: str | None) -> bool:
        """Compatibility wrapper; production callers should use exact bind/clear."""
        with self._lock:
            cur = self._active
            if cur is None or cur.session_id != session_id:
                return False
            if connection_id is None:
                self._active = replace(cur, connection_id=None)
            else:
                self._active = replace(cur, connection_id=str(connection_id))
            return True
