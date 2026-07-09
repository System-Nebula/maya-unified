"""Voice agent tools for game mode session control."""

from __future__ import annotations

from typing import Any, Callable

from tools.registry import ToolSpec


def build_game_mode_tools(*, emit: Callable[..., None] | None = None) -> list[ToolSpec]:
    def start_session(args: dict) -> dict[str, Any]:
        profile_id = str(args.get("profile_id") or args.get("profile") or "pokemon_gba").strip()
        try:
            from services.game.profiles import load_profile

            profile = load_profile(profile_id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        payload = {
            "type": "game.session",
            "action": "start",
            "profile_id": profile.id,
            "display_name": profile.display_name,
        }
        if emit is not None:
            emit(**payload)
        else:
            from services.voice.hub import hub

            hub.broadcast(payload, operator_id=hub._active_operator_id)
        return {
            "ok": True,
            "message": f"Game mode ready for {profile.display_name}. Start the game bridge or use the dashboard Game panel.",
            "profile_id": profile.id,
        }

    def stop_session(_args: dict) -> dict[str, Any]:
        payload = {"type": "game.session", "action": "stop"}
        if emit is not None:
            emit(**payload)
        else:
            from services.voice.hub import hub

            hub.broadcast(payload, operator_id=hub._active_operator_id)
        return {"ok": True, "message": "Game session stop signaled."}

    def send_context(args: dict) -> dict[str, Any]:
        message = str(args.get("message") or "").strip()
        if not message:
            return {"ok": False, "error": "message required"}
        silent = bool(args.get("silent", False))
        payload = {
            "type": "game.context",
            "message": message,
            "silent": silent,
        }
        if emit is not None:
            emit(**payload)
        else:
            from services.voice.hub import hub

            hub.broadcast(payload, operator_id=hub._active_operator_id)
        return {"ok": True, "message": "Context sent to game session."}

    def play_until_goal(args: dict) -> dict[str, Any]:
        goal = str(args.get("goal") or "").strip()
        if not goal:
            return {"ok": False, "error": "goal required"}
        profile_id = str(args.get("profile_id") or args.get("profile") or "pokemon_gba").strip()
        try:
            from services.game.profiles import load_profile

            profile = load_profile(profile_id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        from services.game.neuro_server import game_hub
        from services.voice.hub import hub

        oid = str(args.get("operator_id") or hub._active_operator_id or "").strip()
        if not oid:
            return {"ok": False, "error": "no active operator session"}

        result = game_hub.start_autonomous(oid, goal, profile_id=profile.id)
        if not result.get("ok"):
            return result

        bridge_msg = ""
        try:
            import os

            from services.auth.session import sign_operator_session
            from services.game.bridge_manager import bridge_manager
            from services.game.deps import check_game_bridge_deps, game_bridge_deps_message

            missing = check_game_bridge_deps()
            if missing:
                return {
                    "ok": False,
                    "error": game_bridge_deps_message(missing),
                }

            gateway = os.getenv("MAYA_GATEWAY_URL", "http://127.0.0.1:8090").rstrip("/")
            token = sign_operator_session(oid)
            bridge = bridge_manager.start(
                oid,
                profile_id=profile.id,
                gateway=gateway,
                token=token,
                goal=goal,
            )
            if not bridge.get("ok"):
                return {"ok": False, "error": bridge.get("error") or "bridge failed to start"}
            if bridge.get("ok"):
                bridge_msg = f" Bridge started (pid {bridge.get('pid', '?')})."
        except Exception as exc:  # noqa: BLE001
            bridge_msg = f" Start the bridge from Game mode if needed ({exc})."

        payload = {
            "type": "game.autonomous",
            "action": "start",
            "goal": goal,
            "profile_id": profile.id,
        }
        if emit is not None:
            emit(**payload)
        else:
            hub.broadcast(payload, operator_id=oid)

        return {
            "ok": True,
            "message": (
                f"On it — playing {profile.display_name} until: {goal}. "
                f"I'll narrate every step and keep going on my own.{bridge_msg}"
            ),
            "goal": goal,
            "profile_id": profile.id,
            "bridge_hint": (
                f"python -m apps.game_bridge run --profile {profile.id} "
                f"--goal \"{goal}\" --gateway <gateway> --token <session>"
            ),
        }

    return [
        ToolSpec(
            name="game_start_session",
            description=(
                "Prepare Maya game mode for a vision-based emulator session. "
                "Use when the operator wants to play a game (Pokemon, etc.) via screen capture."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Game profile id (default pokemon_gba).",
                    },
                },
            },
            handler=start_session,
            group="game",
        ),
        ToolSpec(
            name="game_stop_session",
            description="Stop the active game mode session and disconnect the game bridge.",
            parameters={"type": "object", "properties": {}},
            handler=stop_session,
            group="game",
        ),
        ToolSpec(
            name="game_send_context",
            description=(
                "Send a text context update to the game session (maps to Neuro context message)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "What is happening in the game."},
                    "silent": {
                        "type": "boolean",
                        "description": "If true, add context without prompting a response.",
                    },
                },
                "required": ["message"],
            },
            handler=send_context,
            group="game",
        ),
        ToolSpec(
            name="game_play_until_goal",
            description=(
                "Start autonomous VIDEO GAME play on the emulator (mGBA/Pokemon/etc.). "
                "Maya plays by herself, narrates every step via voice, and continues until "
                "the goal is reached on screen. "
                "Use for requests like 'play Pokemon until we beat the game' — "
                "NOT for Discord music, YouTube songs, or voice channels."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": (
                            "Clear win condition visible on screen, e.g. "
                            "'reach Viridian City', 'choose starter Pokemon', "
                            "'beat first gym leader'."
                        ),
                    },
                    "profile_id": {
                        "type": "string",
                        "description": "Game profile id (default pokemon_gba).",
                    },
                },
                "required": ["goal"],
            },
            handler=play_until_goal,
            group="game",
        ),
    ]
