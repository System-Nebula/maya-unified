"""Main game bridge loop — capture, force, act."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from apps.game_bridge.capture import create_capture
from apps.game_bridge.capture.browser import BrowserCapture
from apps.game_bridge.input import create_input
from apps.game_bridge.neuro_client import NeuroClient
from services.game.frame_compare import frame_stable_enough, hash_png_base64
from services.game.profiles import GameProfile, load_profile
from services.game.timing import GameTiming, resolve_game_timing
from services.game.trace import game_trace

log = logging.getLogger("game-bridge.runner")

BRIDGE_FRAME_SESSION = "bridge"
# Min similarity between analysis frame and pre-action frame (0–1).
FRAME_STABILITY_MIN_SIM = 0.85


class GameBridgeRunner:
    def __init__(
        self,
        *,
        profile: GameProfile,
        gateway: str,
        token: str,
        ws_url: str | None = None,
        capture_mode: str | None = None,
    ) -> None:
        self.profile = profile
        self.gateway = gateway.rstrip("/")
        self.token = token
        self.ws_url = ws_url or f"{self.gateway.replace('http', 'ws')}/api/game/neuro?profile={profile.id}"
        cap_pref = capture_mode or profile.capture.get("preferred", "native_window")
        self._capture = create_capture(
            cap_pref,
            title_substring=profile.capture.get("title_substring", ""),
        )
        self._input = create_input(
            profile.input.get("backend", "keyboard"),
            profile.input.get("keymap") or {},
            title_substring=profile.capture.get("title_substring", "mGBA"),
        )
        self._client = NeuroClient(
            self.ws_url,
            token=token,
            game_name=profile.display_name,
        )
        self._session_id: str | None = BRIDGE_FRAME_SESSION
        self._action_names = [a.name for a in profile.actions]
        self._keymap = profile.input.get("keymap") or {}
        self._running = False
        self._last_hash: str | None = None
        self._pending_action: dict[str, Any] | None = None
        self._goal_reached = False
        self._goal: str = ""
        self._autonomous = False
        self._timing = resolve_game_timing(profile)
        self._last_turn_at = 0.0
        self._operator_id = self._resolve_operator_id(token)
        self._turns = 0

        def on_action(data: dict[str, Any]) -> None:
            self._pending_action = data

        def on_session_update(data: dict[str, Any]) -> None:
            if data.get("goal_reached"):
                self._goal_reached = True
                log.info("goal reached: %s", data.get("goal", ""))

        self._client.set_action_handler(on_action)
        self._client.set_session_update_handler(on_session_update)

    @staticmethod
    def _resolve_operator_id(token: str) -> str:
        try:
            from services.auth.session import verify_operator_session

            payload = verify_operator_session(token)
            if payload and payload.get("operator_id"):
                return str(payload["operator_id"])
        except Exception:  # noqa: BLE001
            pass
        return "unknown"

    def _trace(self, event: str, *, level: str = "info", **fields: Any) -> None:
        game_trace(self._operator_id, event, level=level, **fields)

    def _abort_stuck_force(self) -> None:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.post(
                    f"{self.gateway}/api/game/force/abort",
                    headers={"Cookie": f"maya_op_session={self.token}"},
                )
                data = r.json()
                self._trace(
                    "bridge.force_abort",
                    level="warning",
                    status=r.status_code,
                    was_stuck=data.get("was_stuck"),
                )
        except Exception as exc:  # noqa: BLE001
            self._trace("bridge.force_abort_failed", level="warning", error=str(exc)[:200])

    def _upload_frame(self, b64: str) -> dict[str, Any]:
        data_url = b64 if b64.startswith("data:") else f"data:image/png;base64,{b64}"
        return BrowserCapture.upload_http(
            gateway=self.gateway,
            token=self.token,
            image_b64_or_data_url=data_url,
            session_id=self._session_id or BRIDGE_FRAME_SESSION,
            label=self.profile.display_name,
        )

    def _sync_input_hwnd(self) -> None:
        hwnd = getattr(self._capture, "_hwnd", None)
        bind = getattr(self._input, "bind_hwnd", None)
        if hwnd and callable(bind):
            bind(hwnd)

    def _resolve_button(self, action_name: str) -> str | None:
        if action_name in ("wait", "advance_dialog", "press_burst"):
            return None
        if action_name.startswith("press_"):
            return action_name[len("press_") :]
        return action_name

    def _execute_action(self, data: dict[str, Any]) -> tuple[bool, str]:
        action_id = str(data.get("id") or "")
        name = str(data.get("name") or "")
        raw = data.get("data")
        args: dict[str, Any] = {}
        if isinstance(raw, str) and raw.strip():
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {}
        elif isinstance(raw, dict):
            args = raw

        if name == "wait":
            ms = int(args.get("ms") or 400)
            self._input.wait_ms(ms)
            log.info("game action wait %sms", ms)
            self._trace("bridge.action", action=name, ms=ms, ok=True)
            return True, f"waited {ms}ms"

        if name == "advance_dialog":
            count = max(1, min(int(args.get("count") or 6), 12))
            gap_ms = max(80, min(int(args.get("ms") or 140), 400))
            self._sync_input_hwnd()
            button = self._keymap.get("a")
            if not button:
                self._trace("bridge.action", action=name, ok=False, error="no keymap for a")
                return False, "no keymap for a"
            try:
                for _ in range(count):
                    self._input.press("a")
                    self._input.wait_ms(gap_ms)
                log.info("game action advance_dialog %sx", count)
                self._trace(
                    "bridge.action",
                    action=name,
                    count=count,
                    gap_ms=gap_ms,
                    ok=True,
                )
                return True, f"advanced dialog {count}x"
            except Exception as exc:  # noqa: BLE001
                self._trace("bridge.action", action=name, ok=False, error=str(exc)[:200])
                return False, str(exc)

        if name == "press_burst":
            steps = args.get("steps") or []
            if isinstance(steps, str):
                try:
                    steps = json.loads(steps)
                except json.JSONDecodeError:
                    steps = []
            naming = bool(args.get("naming"))
            gap_ms = max(60, min(int(args.get("ms") or (100 if naming else 45)), 200))
            confirm_ms = max(160, min(int(args.get("confirm_ms") or 200), 400))
            self._sync_input_hwnd()
            try:
                pressed = 0
                for step in steps:
                    button = self._resolve_button(str(step))
                    if not button or button not in self._keymap:
                        continue
                    self._input.press(button)
                    if naming and str(step) in ("press_a", "press_b"):
                        self._input.wait_ms(confirm_ms)
                    else:
                        self._input.wait_ms(gap_ms)
                    pressed += 1
                log.info("game action press_burst %sx naming=%s", pressed, naming)
                self._trace(
                    "bridge.action",
                    action=name,
                    count=pressed,
                    gap_ms=gap_ms,
                    ok=True,
                )
                return True, f"burst {pressed}x"
            except Exception as exc:  # noqa: BLE001
                self._trace("bridge.action", action=name, ok=False, error=str(exc)[:200])
                return False, str(exc)

        self._sync_input_hwnd()
        button = self._resolve_button(name)
        if not button:
            self._trace("bridge.action", action=name, ok=False, error="unknown action")
            return False, f"unknown action {name}"
        if button not in self._keymap:
            self._trace("bridge.action", action=name, ok=False, error=f"no keymap for {button}")
            return False, f"no keymap for {button}"
        try:
            self._input.press(button)
            self._input.wait_ms(120)
            log.info("game action %s -> %s", name, button)
            self._trace("bridge.action", action=name, button=button, key=self._keymap.get(button), ok=True)
            return True, f"pressed {button}"
        except Exception as exc:  # noqa: BLE001
            self._trace("bridge.action", action=name, ok=False, error=str(exc)[:200])
            return False, str(exc)

    def _confirm_frame_before_action(
        self,
        force_b64: str,
        action_name: str,
    ) -> tuple[bool, float, str]:
        """Recapture and ensure the screen still matches what vision analyzed."""
        if action_name in ("wait", "advance_dialog", "press_burst") or not force_b64:
            return True, 1.0, "skipped"

        now_b64 = self._capture.capture_png_base64()
        if not now_b64:
            return False, 0.0, "no capture"

        ok, sim = frame_stable_enough(
            force_b64,
            now_b64,
            min_similarity=FRAME_STABILITY_MIN_SIM,
        )
        if ok:
            return True, sim, "stable"

        # One short retry — animations may settle
        time.sleep(0.12)
        retry_b64 = self._capture.capture_png_base64()
        if retry_b64:
            ok, sim = frame_stable_enough(
                force_b64,
                retry_b64,
                min_similarity=FRAME_STABILITY_MIN_SIM,
            )
            if ok:
                return True, sim, "stable_after_retry"

        return False, sim, "stale"

    def _fetch_status(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(
                    f"{self.gateway}/api/game/status",
                    headers={"Cookie": f"maya_op_session={self.token}"},
                )
                data = r.json()
                if data.get("ok"):
                    return data.get("session") or {}
        except Exception as exc:  # noqa: BLE001
            log.debug("status poll failed: %s", exc)
        return {}

    def _refresh_timing(self) -> None:
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(
                    f"{self.gateway}/api/game/timing",
                    params={"profile_id": self.profile.id},
                    headers={"Cookie": f"maya_op_session={self.token}"},
                )
                data = r.json()
                if data.get("ok") and isinstance(data.get("timing"), dict):
                    self._timing = GameTiming.from_dict(data["timing"])
        except Exception as exc:  # noqa: BLE001
            log.debug("timing refresh failed: %s", exc)

    def _sync_goal_from_server(self) -> None:
        st = self._fetch_status()
        goal = str(st.get("goal") or "").strip()
        if goal:
            self._goal = goal
            self._autonomous = bool(st.get("autonomous", True))
        if st.get("goal_reached"):
            self._goal_reached = True

    def run(
        self,
        *,
        max_turns: int | None = None,
        goal: str = "",
        autonomous: bool = False,
    ) -> None:
        self._refresh_timing()
        policy = self.profile.turn_policy
        default_query = str(policy.get("force_query") or "Pick an action.")
        poll_ms = self._timing.poll_ms
        turns = 0

        self._goal = (goal or "").strip()
        self._autonomous = autonomous or bool(self._goal)
        if self._autonomous and not self._goal:
            self._sync_goal_from_server()
        elif not self._goal:
            self._sync_goal_from_server()

        if self._goal and not autonomous:
            self._autonomous = True

        self._client.connect()
        self._client.startup()
        self._client.drain_startup_ack()
        self._client.register_actions(self.profile.neuro_actions())
        self._running = True
        log.info("game bridge running profile=%s operator=%s", self.profile.id, self._operator_id)
        self._trace("bridge.start", profile=self.profile.id, goal=self._goal, autonomous=self._autonomous)

        no_frame_streak = 0
        try:
            while self._running:
                if self._goal_reached:
                    log.info("stopping — goal reached")
                    break
                if max_turns is not None and turns >= max_turns and not self._autonomous:
                    break

                b64 = self._capture.capture_png_base64()
                if not b64:
                    no_frame_streak += 1
                    if no_frame_streak == 1:
                        log.warning(
                            "no capture frame — install game deps (uv sync --extra game), "
                            "focus mGBA, or use dashboard Share emulator"
                        )
                        self._trace("bridge.no_capture", level="warning")
                    if no_frame_streak >= 30:
                        log.error("capture failed 30 times — stopping bridge")
                        break
                    time.sleep(poll_ms / 1000.0)
                    continue
                no_frame_streak = 0

                upload = self._upload_frame(b64)
                self._session_id = upload.get("session_id") or self._session_id
                content_hash = upload.get("content_hash")
                if content_hash:
                    self._last_hash = content_hash

                if self._last_turn_at:
                    elapsed_ms = (time.monotonic() - self._last_turn_at) * 1000
                    if elapsed_ms < self._timing.min_analysis_gap_ms:
                        time.sleep(poll_ms / 1000.0)
                        continue

                ref = upload.get("frame_ref")
                if not ref:
                    log.warning("upload missing frame_ref")
                    time.sleep(poll_ms / 1000.0)
                    continue
                self._session_id = upload.get("session_id") or self._session_id
                self._pending_action = None
                self._goal_reached = False

                if self._autonomous and self._goal:
                    query = (
                        "Pick the next action. Name/gender menus: arrows to cursor, A to select. "
                        "say only on stream highlights."
                    )
                    state = f"GOAL: {self._goal}"
                    if st := self._fetch_status():
                        prog = st.get("goal_progress")
                        if prog:
                            state += f"\nProgress: {prog}"
                else:
                    query = default_query
                    state = ""

                force_b64 = b64
                force_hash = hash_png_base64(b64) if b64 else ""

                self._client.force_actions(
                    action_names=self._action_names,
                    query=query,
                    state=state,
                    frame_ref=ref,
                    image=b64,
                    goal=self._goal,
                    autonomous=self._autonomous,
                )
                self._trace("bridge.force_sent", frame_ref=ref, turn=self._turns + 1)

                deadline = time.monotonic() + 70.0
                while self._pending_action is None and time.monotonic() < deadline:
                    time.sleep(0.05)

                action_data = self._pending_action
                if not action_data:
                    log.warning("action timeout — aborting stuck force")
                    self._trace("bridge.action_timeout", level="warning", waited_s=70)
                    self._abort_stuck_force()
                    continue

                action_name = str(action_data.get("name") or "")
                stable, sim, reason = self._confirm_frame_before_action(force_b64, action_name)
                if not stable:
                    log.warning(
                        "stale frame — skipping %s (sim=%.2f, %s)",
                        action_name,
                        sim,
                        reason,
                    )
                    self._trace(
                        "bridge.stale_frame",
                        level="warning",
                        action=action_name,
                        similarity=round(sim, 3),
                        reason=reason,
                        force_hash=force_hash,
                    )
                    self._client.action_result(
                        str(action_data.get("id") or ""),
                        success=False,
                        message=f"stale frame sim={sim:.2f}",
                    )
                    continue

                try:
                    ok, message = self._execute_action(action_data)
                except Exception as exc:  # noqa: BLE001
                    log.exception("action execution failed: %s", action_data.get("name"))
                    ok, message = False, str(exc)
                self._client.action_result(
                    str(action_data.get("id") or ""),
                    success=ok,
                    message=message,
                )
                turns += 1
                self._turns = turns

                st = self._fetch_status()
                if st.get("goal_reached"):
                    self._goal_reached = True
                    log.info("goal reached (status): %s", st.get("goal", ""))

                pause_ms = self._timing.turn_pause_ms(
                    str(st.get("last_say") or ""),
                    naming_active=bool(st.get("naming_active")),
                )
                log.debug(
                    "turn pause %sms (fps %.2f–%.2f) after say len=%s",
                    pause_ms,
                    self._timing.analysis_fps_min,
                    self._timing.analysis_fps_max,
                    len(str(st.get("last_say") or "")),
                )
                time.sleep(pause_ms / 1000.0)
                self._last_turn_at = time.monotonic()
                if turns % 5 == 0:
                    self._refresh_timing()
        finally:
            self._running = False
            self._trace("bridge.stop", turns=self._turns)
            self._client.close()
            close = getattr(self._capture, "close", None)
            if callable(close):
                close()
            try:
                with httpx.Client(timeout=10.0) as client:
                    client.post(
                        f"{self.gateway}/api/game/session/stop",
                        headers={"Cookie": f"maya_op_session={self.token}"},
                    )
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._running = False
