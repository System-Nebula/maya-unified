"""Neuro API session state machine for a connected game client."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger("maya-unified.game.neuro_session")

SendFn = Callable[[dict[str, Any]], Awaitable[None]]
RunForceFn = Callable[["NeuroSession", dict[str, Any]], Awaitable[None]]


@dataclass
class RegisteredAction:
    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class NeuroSession:
    operator_id: str
    session_id: str
    game_name: str = ""
    actions: dict[str, RegisteredAction] = field(default_factory=dict)
    force_in_progress: bool = False
    pending_force: dict[str, Any] | None = None
    in_flight_action_id: str | None = None
    in_flight_action_name: str | None = None
    last_force_id: str | None = None
    # Autonomous goal-driven play
    goal: str = ""
    autonomous: bool = False
    goal_reached: bool = False
    goal_progress: str = ""
    profile_id: str = "pokemon_gba"
    turn_count: int = 0
    turn_history: list[dict[str, Any]] = field(default_factory=list)
    # Vision-guided name entry (LLM picks every button from the screenshot)
    naming_queue: list[str] = field(default_factory=list)
    naming_target: str = ""
    naming_cursor: tuple[int, int] = (0, 0)
    naming_pending_verify: str = ""
    names_spelled: list[str] = field(default_factory=list)
    # Restored when bridge rejects action (stale frame)
    naming_last_popped: str = ""
    naming_last_burst: list[str] = field(default_factory=list)
    naming_known_entered: str = ""
    naming_queue_entered: str = ""
    naming_typed_letters: int = 0
    _pre_action_cursor: tuple[int, int] | None = field(default=None, repr=False)

    @property
    def naming_active(self) -> bool:
        return bool(self.naming_queue or self.naming_target or self.naming_pending_verify)
    # Detect stuck interact loops (NES bedroom, NPC spam) on similar frames
    last_force_b64: str = ""
    unchanged_force_streak: int = 0
    _send: SendFn | None = field(default=None, repr=False)
    _run_force: RunForceFn | None = field(default=None, repr=False)

    def set_autonomous_goal(self, goal: str, *, autonomous: bool = True) -> None:
        self.goal = (goal or "").strip()
        self.autonomous = autonomous and bool(self.goal)
        self.goal_reached = False
        self.goal_progress = ""
        self.turn_count = 0
        self.turn_history.clear()
        self.naming_queue.clear()
        self.naming_target = ""
        self.naming_cursor = (0, 0)
        self.naming_pending_verify = ""
        self.naming_known_entered = ""
        self.naming_queue_entered = ""
        self.naming_typed_letters = 0
        self.names_spelled.clear()
        self.last_force_b64 = ""
        self.unchanged_force_streak = 0

    def stop_autonomous(self) -> None:
        self.autonomous = False

    def record_turn(
        self,
        *,
        action: str,
        say: str,
        goal_progress: str,
        goal_reached: bool,
    ) -> None:
        self.turn_count += 1
        entry = {
            "turn": self.turn_count,
            "action": action,
            "say": say,
            "goal_progress": goal_progress,
            "goal_reached": goal_reached,
        }
        self.turn_history.append(entry)
        if len(self.turn_history) > 20:
            self.turn_history = self.turn_history[-20:]
        if goal_progress:
            self.goal_progress = goal_progress
        if goal_reached:
            self.goal_reached = True
            self.autonomous = False

    def undo_last_turn(self) -> None:
        """Roll back the last recorded turn (e.g. action skipped on stale frame)."""
        if not self.turn_history:
            return
        self.turn_history.pop()
        self.turn_count = max(0, self.turn_count - 1)
        if self.turn_history:
            last = self.turn_history[-1]
            self.goal_progress = str(last.get("goal_progress") or "")
        else:
            self.goal_progress = ""

    def clear_pending_goal(self) -> None:
        """Called when goal completes — stops autonomous loop."""
        self.autonomous = False

    def bind(self, send: SendFn, run_force: RunForceFn) -> None:
        self._send = send
        self._run_force = run_force

    async def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        command = str(msg.get("command") or "").strip()
        game = str(msg.get("game") or "").strip()
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}

        if command == "startup":
            self.game_name = game
            self.actions.clear()
            self.force_in_progress = False
            self.pending_force = None
            self.in_flight_action_id = None
            self.in_flight_action_name = None
            await self._emit_startup_ack()
            return {"ok": True, "command": "startup"}

        if game and self.game_name and game != self.game_name:
            return {"ok": False, "error": f"game mismatch: expected {self.game_name!r}"}

        if command == "actions/register":
            return await self._register_actions(data)
        if command == "actions/unregister":
            return await self._unregister_actions(data)
        if command == "actions/force":
            return await self._force_actions(data, game=game or self.game_name)
        if command == "action/result":
            return await self._action_result(data)
        if command == "context":
            return {"ok": True, "command": "context"}

        return {"ok": False, "error": f"unknown command: {command}"}

    async def _emit_startup_ack(self) -> None:
        if self._send is None:
            return
        await self._send(
            {
                "command": "startup",
                "data": {
                    "session": {
                        "sessionId": self.session_id,
                        "characterId": "maya",
                        "displayName": "Maya",
                    }
                },
            }
        )

    async def _register_actions(self, data: dict[str, Any]) -> dict[str, Any]:
        raw = data.get("actions") or []
        added = 0
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if name in self.actions:
                continue
            schema = item.get("schema")
            self.actions[name] = RegisteredAction(
                name=name,
                description=str(item.get("description") or name),
                schema=dict(schema) if isinstance(schema, dict) else {},
            )
            added += 1
        return {"ok": True, "registered": added}

    async def _unregister_actions(self, data: dict[str, Any]) -> dict[str, Any]:
        names = data.get("action_names") or []
        removed = 0
        for raw in names:
            name = str(raw).strip()
            if name in self.actions:
                del self.actions[name]
                removed += 1
        if self.force_in_progress and self.pending_force:
            allowed = set(self.pending_force.get("action_names") or [])
            if allowed and not allowed.intersection(self.actions.keys()):
                self.force_in_progress = False
                self.pending_force = None
        return {"ok": True, "removed": removed}

    async def _force_actions(self, data: dict[str, Any], *, game: str) -> dict[str, Any]:
        if self.force_in_progress:
            from services.game.trace import game_trace

            game_trace(
                self.operator_id,
                "gateway.force_rejected",
                level="warning",
                error="action force already in progress",
                in_flight=self.in_flight_action_name,
            )
            return {"ok": False, "error": "action force already in progress"}
        action_names = [str(n).strip() for n in (data.get("action_names") or []) if str(n).strip()]
        if not action_names:
            return {"ok": False, "error": "action_names required"}
        unknown = [n for n in action_names if n not in self.actions]
        if unknown:
            return {"ok": False, "error": f"unregistered actions: {unknown}"}

        force_id = uuid.uuid4().hex[:12]
        self.last_force_id = force_id
        self.force_in_progress = True
        self.pending_force = {
            "force_id": force_id,
            "game": game,
            "state": str(data.get("state") or ""),
            "query": str(data.get("query") or "Pick an action."),
            "action_names": action_names,
            "priority": str(data.get("priority") or "low"),
            "ephemeral_context": bool(data.get("ephemeral_context", False)),
            "frame_ref": data.get("frame_ref"),
            "image": data.get("image"),
            "goal": str(data.get("goal") or self.goal or ""),
            "autonomous": bool(data.get("autonomous", self.autonomous)),
        }
        if self._run_force is not None:
            await self._run_force(self, self.pending_force)
        return {"ok": True, "force_id": force_id}

    async def send_action(self, name: str, data: dict[str, Any] | None = None) -> str:
        action_id = uuid.uuid4().hex[:12]
        self.in_flight_action_id = action_id
        self.in_flight_action_name = name
        payload: dict[str, Any] = {
            "command": "action",
            "data": {
                "id": action_id,
                "name": name,
            },
        }
        if data:
            payload["data"]["data"] = json.dumps(data)
        if self._send is not None:
            await self._send(payload)
        return action_id

    async def _action_result(self, data: dict[str, Any]) -> dict[str, Any]:
        action_id = str(data.get("id") or "")
        success = bool(data.get("success"))
        message = str(data.get("message") or "")

        if self.in_flight_action_id and action_id and action_id != self.in_flight_action_id:
            log.warning("action result id mismatch: got %s expected %s", action_id, self.in_flight_action_id)

        stale = (not success) and message.startswith("stale frame")
        if stale:
            from services.game.trace import game_trace

            skipped = self.in_flight_action_name or ""
            self.undo_last_turn()
            if self.naming_last_burst:
                self.naming_queue = list(self.naming_last_burst) + self.naming_queue
                self.naming_last_burst = []
            elif self.naming_last_popped:
                self.naming_queue.insert(0, self.naming_last_popped)
                self.naming_last_popped = ""
            if self._pre_action_cursor is not None:
                self.naming_cursor = self._pre_action_cursor
                self._pre_action_cursor = None
            game_trace(
                self.operator_id,
                "gateway.stale_frame",
                level="warning",
                skipped_action=skipped,
                message=message[:120],
            )
        elif success:
            self.naming_last_popped = ""
            self.naming_last_burst = []
            self._pre_action_cursor = None

        retry = False
        if not success and self.pending_force and not stale:
            retry = True

        self.in_flight_action_id = None
        self.in_flight_action_name = None
        self.force_in_progress = False

        result = {
            "ok": True,
            "success": success,
            "message": message,
            "retry": retry,
        }
        self.pending_force = None
        return result

    def complete_force_without_result(self) -> None:
        """Called when agent fails to pick an action."""
        self.force_in_progress = False
        self.in_flight_action_id = None
        self.in_flight_action_name = None
        self.pending_force = None

    def abort_force(self, *, reason: str = "") -> dict[str, Any]:
        """Clear a stuck force (e.g. bridge action timeout)."""
        was_stuck = self.force_in_progress
        self.complete_force_without_result()
        if reason:
            log.warning("force aborted: %s", reason)
        return {"ok": True, "was_stuck": was_stuck}
