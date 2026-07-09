"""Neuro-compatible game WebSocket hub and connection manager."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from services.game.agent_loop import run_force
from services.game.neuro_session import NeuroSession

log = logging.getLogger("maya-unified.game.neuro_server")


@dataclass
class GameConnection:
    operator_id: str
    session_id: str
    neuro: NeuroSession
    websocket: Any = field(default=None, repr=False)
    connected: bool = True
    profile_id: str = ""


class GameHub:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_operator: dict[str, GameConnection] = {}
        self._pending_autonomous: dict[str, dict[str, Any]] = {}

    def get(self, operator_id: str) -> GameConnection | None:
        return self._by_operator.get(str(operator_id))

    def start_autonomous(
        self,
        operator_id: str,
        goal: str,
        *,
        profile_id: str = "",
    ) -> dict[str, Any]:
        oid = str(operator_id)
        goal = (goal or "").strip()
        if not goal:
            return {"ok": False, "error": "goal required"}
        pending = {"goal": goal, "profile_id": profile_id, "autonomous": True}
        self._pending_autonomous[oid] = pending
        conn = self.get(oid)
        if conn is not None:
            conn.neuro.set_autonomous_goal(goal, autonomous=True)
            if profile_id:
                conn.profile_id = profile_id
                conn.neuro.profile_id = profile_id
        self._broadcast_event(
            oid,
            {
                "type": "game.autonomous",
                "action": "start",
                "goal": goal,
                "profile_id": profile_id,
            },
        )
        return {"ok": True, "goal": goal, "connected": conn is not None}

    def stop_autonomous(self, operator_id: str) -> dict[str, Any]:
        oid = str(operator_id)
        self._pending_autonomous.pop(oid, None)
        conn = self.get(oid)
        if conn is not None:
            conn.neuro.stop_autonomous()
        self._broadcast_event(oid, {"type": "game.autonomous", "action": "stop"})
        return {"ok": True}

    def on_goal_reached(self, operator_id: str) -> None:
        self._pending_autonomous.pop(str(operator_id), None)

    def abort_force(self, operator_id: str, *, reason: str = "") -> dict[str, Any]:
        conn = self.get(str(operator_id))
        if conn is None:
            return {"ok": True, "was_stuck": False, "connected": False}
        result = conn.neuro.abort_force(reason=reason)
        from services.game.trace import game_trace

        game_trace(
            operator_id,
            "gateway.force_abort",
            level="warning",
            was_stuck=result.get("was_stuck"),
            reason=reason,
        )
        return {**result, "connected": True}

    async def attach(
        self,
        operator_id: str,
        websocket: Any,
        *,
        profile_id: str = "",
    ) -> GameConnection:
        oid = str(operator_id)
        session_id = uuid.uuid4().hex[:12]
        neuro = NeuroSession(operator_id=oid, session_id=session_id)

        async def send(payload: dict[str, Any]) -> None:
            await websocket.send_text(json.dumps(payload))

        async def on_force(session: NeuroSession, force: dict[str, Any]) -> None:
            from services.game.agent_loop import vision_timeout_s
            from services.game.trace import game_trace

            force_id = str(force.get("force_id") or "")
            game_trace(
                session.operator_id,
                "vision.force_start",
                force_id=force_id,
                goal=force.get("goal") or session.goal,
            )
            started = time.monotonic()
            timeout_s = vision_timeout_s(session.profile_id or "pokemon_gba")
            try:
                await asyncio.wait_for(run_force(session, force), timeout=timeout_s)
            except asyncio.TimeoutError:
                elapsed = round(time.monotonic() - started, 2)
                game_trace(
                    session.operator_id,
                    "vision.timeout",
                    level="error",
                    force_id=force_id,
                    elapsed_s=elapsed,
                )
                if session.force_in_progress:
                    session.complete_force_without_result()
                    await session.send_action("wait", {"ms": 500})
            except Exception as exc:  # noqa: BLE001
                elapsed = round(time.monotonic() - started, 2)
                game_trace(
                    session.operator_id,
                    "vision.error",
                    level="error",
                    force_id=force_id,
                    elapsed_s=elapsed,
                    error=str(exc)[:300],
                )
                if session.force_in_progress:
                    session.complete_force_without_result()
                    await session.send_action("wait", {"ms": 500})

        neuro.bind(send, on_force)
        pending = self._pending_autonomous.get(oid)
        resolved_profile = str(profile_id or (pending or {}).get("profile_id") or "pokemon_gba")
        neuro.profile_id = resolved_profile

        def _apply_op_context() -> None:
            try:
                from services.voice.hub import hub

                hub.apply_operator_context(oid)
            except Exception as exc:  # noqa: BLE001
                log.debug("game attach: apply_operator_context failed: %s", exc)

        await asyncio.to_thread(_apply_op_context)

        conn = GameConnection(
            operator_id=oid,
            session_id=session_id,
            neuro=neuro,
            websocket=websocket,
            profile_id=str(profile_id or ""),
        )
        pending = self._pending_autonomous.get(oid)
        if pending:
            neuro.set_autonomous_goal(pending["goal"], autonomous=True)
            if pending.get("profile_id"):
                conn.profile_id = str(pending["profile_id"])
                neuro.profile_id = conn.profile_id
        async with self._lock:
            old = self._by_operator.get(oid)
            if old and old.websocket is not None and old is not conn:
                try:
                    await old.websocket.close()
                except Exception:  # noqa: BLE001
                    pass
            self._by_operator[oid] = conn
        return conn

    async def detach(self, operator_id: str) -> None:
        async with self._lock:
            conn = self._by_operator.pop(str(operator_id), None)
        if conn:
            conn.connected = False

    async def handle_message(self, operator_id: str, raw: str) -> dict[str, Any] | None:
        conn = self.get(operator_id)
        if conn is None:
            return {"ok": False, "error": "no session"}
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "error": "invalid json"}
        if not isinstance(msg, dict):
            return {"ok": False, "error": "expected object"}
        result = await conn.neuro.handle(msg)
        self._broadcast_event(operator_id, {"type": "game.event", "command": msg.get("command"), "result": result})
        return result

    def status(self, operator_id: str) -> dict[str, Any]:
        conn = self.get(operator_id)
        pending = self._pending_autonomous.get(str(operator_id))
        if conn is None:
            if pending:
                return {
                    "connected": False,
                    "autonomous": True,
                    "goal": pending.get("goal", ""),
                    "goal_reached": False,
                    "profile_id": pending.get("profile_id", ""),
                }
            return {"connected": False}
        neuro = conn.neuro
        return {
            "connected": conn.connected,
            "session_id": conn.session_id,
            "game": neuro.game_name,
            "profile_id": conn.profile_id,
            "actions_registered": len(neuro.actions),
            "force_in_progress": neuro.force_in_progress,
            "in_flight_action": neuro.in_flight_action_name,
            "goal": neuro.goal,
            "autonomous": neuro.autonomous,
            "goal_reached": neuro.goal_reached,
            "goal_progress": neuro.goal_progress,
            "turn_count": neuro.turn_count,
            "last_say": (neuro.turn_history[-1].get("say") or "") if neuro.turn_history else "",
            "naming_active": neuro.naming_active,
        }

    def _broadcast_event(self, operator_id: str, event: dict[str, Any]) -> None:
        try:
            from services.voice.hub import hub

            hub.broadcast({**event, "operator_id": operator_id}, operator_id=operator_id)
        except Exception:  # noqa: BLE001
            pass


game_hub = GameHub()
