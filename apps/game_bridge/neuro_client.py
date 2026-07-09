"""Neuro WebSocket client for game bridge."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any, Callable

log = logging.getLogger("game-bridge.neuro_client")


class NeuroClient:
    def __init__(self, ws_url: str, *, token: str = "", game_name: str = "") -> None:
        self.ws_url = self._with_token(ws_url, token)
        self.game_name = game_name
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._running = False
        self._on_action: Callable[[dict[str, Any]], None] | None = None
        self._on_session_update: Callable[[dict[str, Any]], None] | None = None

    @staticmethod
    def _with_token(url: str, token: str) -> str:
        if not token:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={token}"

    def set_action_handler(self, fn: Callable[[dict[str, Any]], None]) -> None:
        self._on_action = fn

    def set_session_update_handler(self, fn: Callable[[dict[str, Any]], None]) -> None:
        self._on_session_update = fn

    def connect(self) -> None:
        try:
            import websocket  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("websocket-client package required") from exc

        self._running = True
        self._ws = websocket.WebSocket()
        self._ws.connect(self.ws_url)
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._ws = None

    def _reader(self) -> None:
        while self._running and self._ws is not None:
            try:
                raw = self._ws.recv()
                if not raw:
                    break
                msg = json.loads(raw)
                if isinstance(msg, dict) and msg.get("command") == "action":
                    if self._on_action:
                        self._on_action(msg.get("data") or {})
                    else:
                        self._inbox.put(msg)
                elif isinstance(msg, dict) and msg.get("command") == "session/update":
                    data = msg.get("data") or {}
                    if self._on_session_update:
                        self._on_session_update(data)
                    else:
                        self._inbox.put(msg)
                else:
                    self._inbox.put(msg)
            except Exception as exc:  # noqa: BLE001
                if self._running:
                    log.debug("ws recv ended: %s", exc)
                break

    def send(self, command: str, data: dict[str, Any] | None = None) -> None:
        if self._ws is None:
            raise RuntimeError("not connected")
        payload: dict[str, Any] = {"command": command, "game": self.game_name}
        if data is not None:
            payload["data"] = data
        self._ws.send(json.dumps(payload))

    def startup(self) -> None:
        self.send("startup")

    def register_actions(self, actions: list[dict[str, Any]]) -> None:
        self.send("actions/register", {"actions": actions})

    def force_actions(
        self,
        *,
        action_names: list[str],
        query: str,
        state: str = "",
        frame_ref: str | None = None,
        image: str | None = None,
        goal: str = "",
        autonomous: bool = False,
    ) -> None:
        data: dict[str, Any] = {
            "action_names": action_names,
            "query": query,
            "state": state,
        }
        if frame_ref:
            data["frame_ref"] = frame_ref
        if image:
            data["image"] = image
        if goal:
            data["goal"] = goal
        if autonomous:
            data["autonomous"] = True
        self.send("actions/force", data)

    def action_result(self, action_id: str, *, success: bool, message: str = "") -> None:
        self.send(
            "action/result",
            {"id": action_id, "success": success, "message": message},
        )

    def wait_action(self, timeout: float = 60.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = self._inbox.get(timeout=0.25)
            except queue.Empty:
                continue
            if msg.get("command") == "action":
                return msg.get("data") or {}
        return None

    def drain_startup_ack(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = self._inbox.get(timeout=0.25)
            except queue.Empty:
                continue
            if msg.get("command") == "startup":
                return
