"""Vision LLM picks game actions with in-character narration and goal tracking."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from services.game.frames import resolve_frame_bytes
from services.game.frame_compare import frame_similarity
from services.game.frlg_playbook import SCREEN_STATE_GUIDE, milestone_context
from services.game.lmstudio_reasoning import (
    normalize_lmstudio_reasoning_effort,
    think_prefix_for_model,
)
from services.game.naming_playbook import normalize_entered_name
from services.game.llm_json import parse_llm_json_dict
from services.game.naming_vision import parse_entered_from_prose
from services.game.narration import emit_game_chat_line, prepare_game_say, speak_game_line
from services.game.neuro_session import NeuroSession
from services.game.profiles import load_profile

log = logging.getLogger("maya-unified.game.agent")


def _maya_personality_prompt() -> str:
    try:
        from services.voice.hub import hub

        if hub.ready and hub.agent is not None:
            # Game loop must NOT inherit voice TTS "VOICE:" delivery instructions.
            return hub.agent.llm.base_system_prompt(include_style_cue=False)
    except Exception:  # noqa: BLE001
        pass
    return (
        "You are Maya — polished egirl VTuber streamer playing live on camera. "
        "Confident, flowy, witty; never robotic or play-by-play."
    )


def _game_play_prompt(
    *,
    goal: str,
    autonomous: bool,
    allowed_actions: list[str],
    profile_guide: str = "",
    vision_thinking: bool = False,
) -> str:
    base = _maya_personality_prompt()
    goal_block = ""
    if goal:
        goal_block = (
            f"\n\n## Current mission\n"
            f"GOAL: {goal}\n"
            "Play autonomously toward this goal. Do not ask the user what to do next — "
            "decide the next button press yourself every turn.\n"
            "Set goal_reached to true ONLY when the screenshot clearly shows the goal is done."
        )
    elif autonomous:
        goal_block = (
            "\n\nPlay autonomously — decide each step yourself without asking the user."
        )
    actions_list = ", ".join(sorted(allowed_actions))
    guide_block = ""
    if profile_guide.strip():
        guide_block = f"\n\n{profile_guide.strip()}\n"
    think_block = ""
    if vision_thinking:
        think_block = (
            "\nBefore choosing `action`, reason about: (1) what screen/state this is, "
            "(2) whether pressing A would repeat the last interaction or trap, "
            "(3) the single best button to advance the goal.\n"
        )
    return (
        f"{base}\n\n"
        "You are playing a video game via button presses. Each turn: screenshot in, one action out.\n"
        f'Allowed actions (pick EXACTLY one for "action"): {actions_list}\n'
        "'say' is optional spoken VTuber commentary — NEVER use 'say' as the action value.\n\n"
        "**Action first, talk second.** Every turn MUST have a valid action. "
        "Leave `say` empty on most turns (menus, walking, naming, grinding). "
        "Only `say` after a highlight — battles, funny NPCs, Gary, Eevee, milestones.\n"
        "Never output VOICE: lines or delivery cues — those are for voice chat only, not game mode.\n"
        "Never use \"say\" as the action value. Pick a button press every turn.\n"
        "On letter-name grids and Boy/Girl menus: use press_up/down/left/right to move the cursor, "
        "then press_a on the correct cell. Do not press_a until the cursor is on the right option.\n"
        "On the name grid you MUST use left/right — letters span 9 columns. Never mash press_a.\n"
        "Spell trainer name MAYA letter-by-letter: move cursor, then A. Rival name is GARY.\n"
        "**Screen check:** If the screenshot is NOT normal Pokemon gameplay (NES/SNES minigame, "
        "Game Corner slots, link-cable toy, title screen, or a menu you did not expect): "
        "use press_b or arrows to exit — do NOT press_a. On overworld, walk with arrows; "
        "only press_a when facing an NPC or to advance a visible text box.\n"
        "Play quickly. Prefer arrows + A over wait on static screens.\n"
        "Never announce button names in `say`.\n"
        f"{think_block}"
        f"{guide_block}"
        f"{goal_block}\n\n"
        "Respond with ONLY valid JSON (no markdown):\n"
        "{\n"
        f'  "action": "<one of: {actions_list}>",\n'
        '  "data": {},\n'
        '  "say": "<optional VTuber line — empty string if routine>",\n'
        '  "goal_reached": false,\n'
        '  "goal_progress": "<brief status toward the goal>"\n'
        "}"
    )


def _load_profile_guide(profile_id: str) -> str:
    try:
        profile = load_profile(profile_id)
    except Exception:  # noqa: BLE001
        return ""
    parts: list[str] = []
    if profile.prompt_guide.strip():
        parts.append(profile.prompt_guide.strip())
    if profile_id in ("pokemon_gba", "pokemon_firered", "pokemon_leafgreen"):
        parts.append(SCREEN_STATE_GUIDE.strip())
    pb = profile.playbook
    trainer = str(pb.get("trainer_name") or "").strip()
    rival = str(pb.get("rival_name") or "").strip()
    favorites = pb.get("favorite_pokemon") or []
    if trainer or rival:
        bits = []
        if trainer:
            bits.append(f"trainer name {trainer}")
        if rival:
            bits.append(f"rival name {rival}")
        parts.append("In-game names: " + "; ".join(bits) + ".")
    if favorites:
        names = ", ".join(str(x) for x in favorites if str(x).strip())
        if names:
            parts.append(f"Favorite Pokemon: {names}.")
    return "\n\n".join(parts)


def _normalize_action(raw: str, allowed: set[str]) -> str | None:
    """Map model output to an allowed action name when possible."""
    text = (raw or "").strip()
    if not text:
        return None
    if text in allowed:
        return text
    key = text.lower().replace("-", "_").replace(" ", "_")
    if key in allowed:
        return key
    compact = key.replace("_", "")
    for candidate in allowed:
        if candidate.lower() == key or candidate.lower().replace("_", "") == compact:
            return candidate
    alias_map = {
        "a": "press_a",
        "b": "press_b",
        "up": "press_up",
        "down": "press_down",
        "left": "press_left",
        "right": "press_right",
        "start": "press_start",
        "select": "press_select",
        "advance_dialog": "advance_dialog",
        "a_until_end_of_dialog": "advance_dialog",
        "dialog": "advance_dialog",
    }
    alias = alias_map.get(key) or alias_map.get(compact.removeprefix("press"))
    if alias and alias in allowed:
        return alias
    return None


def _recover_action(data: dict[str, Any], allowed: set[str], raw: str) -> tuple[str | None, str]:
    """Best-effort action recovery when the model mislabels fields."""
    say_extra = ""
    action_raw = str(data.get("action") or "").strip()
    if action_raw.lower().startswith("voice:"):
        action_raw = ""

    norm = _normalize_action(action_raw, allowed)
    if norm:
        return norm, say_extra

    if action_raw.lower() == "say":
        say_text = str(data.get("say") or "")
        for token in re.findall(r"[A-Za-z_]+", say_text):
            norm = _normalize_action(token, allowed)
            if norm and norm != "wait":
                return norm, say_extra
        for alt_key in ("button", "key", "input", "move", "choice", "press"):
            norm = _normalize_action(str(data.get(alt_key) or ""), allowed)
            if norm and norm != "wait":
                return norm, say_extra
        inferred = _infer_action_from_raw(raw, allowed)
        if inferred and inferred != "wait":
            return inferred, say_extra

    if action_raw and action_raw.lower() not in {"say", "action"} and (
        action_raw.lower().startswith("voice:") or " " in action_raw or len(action_raw) > 24
    ):
        say_extra = action_raw

    for key, val in data.items():
        if key in {"say", "goal_progress", "goal_reached", "data", "action"}:
            continue
        if isinstance(val, str):
            norm = _normalize_action(val, allowed)
            if norm:
                return norm, say_extra

    for name in sorted(allowed, key=len, reverse=True):
        if re.search(rf'["\']{re.escape(name)}["\']', raw, re.I):
            return name, say_extra

    inferred = _infer_action_from_raw(raw, allowed)
    if inferred:
        return inferred, say_extra

    return None, say_extra


def _infer_action_from_raw(raw: str, allowed: set[str]) -> str | None:
    """Last resort: find an allowed action name in model output."""
    text = raw or ""
    for name in sorted(allowed, key=len, reverse=True):
        if re.search(rf'["\']action["\']\s*:\s*["\']{re.escape(name)}["\']', text, re.I):
            return name
        if re.search(rf"\b{re.escape(name)}\b", text, re.I):
            return name
    return None


def _pick_game_llm_text(resp, *, purpose: str = "turn") -> str:
    """Prefer visible content; for probes/naming accept any JSON blob."""
    content = _strip_thinking_content((getattr(resp, "content", None) or "").strip())
    reasoning = _strip_thinking_content(
        (getattr(resp, "reasoning_content", None) or "").strip()
    )

    if purpose in ("probe", "naming"):
        for candidate in (content, reasoning):
            if candidate and "{" in candidate:
                return candidate
        return content or reasoning

    if content and "{" in content and '"action"' in content:
        return content
    if reasoning and '"action"' in reasoning:
        return reasoning
    return content or reasoning


def _recent_actions(session: NeuroSession, n: int = 6) -> list[str]:
    return [str(t.get("action") or "") for t in session.turn_history[-n:]]


def _a_press_streak(session: NeuroSession) -> int:
    streak = 0
    for act in reversed(_recent_actions(session, 8)):
        if act in ("press_a", "advance_dialog"):
            streak += 1
        else:
            break
    return streak


def _update_force_streak(session: NeuroSession, image_bytes: bytes | None) -> None:
    """Track how many turns the scene has stayed nearly identical."""
    if not image_bytes:
        return
    import base64

    b64 = base64.b64encode(image_bytes).decode("ascii")
    if session.last_force_b64:
        sim = frame_similarity(session.last_force_b64, b64)
        if sim >= 0.92:
            session.unchanged_force_streak += 1
        else:
            session.unchanged_force_streak = 0
    session.last_force_b64 = b64


def _escape_arrows(allowed: set[str]) -> list[str]:
    """Preferred walk-away order: down first (bedroom stairs), then lateral."""
    order = ("press_down", "press_left", "press_right", "press_up")
    return [a for a in order if a in allowed]


def _clear_naming(session: NeuroSession) -> None:
    session.naming_queue.clear()
    session.naming_target = ""
    session.naming_pending_verify = ""
    session.naming_last_popped = ""
    session.naming_last_burst = []
    session.naming_known_entered = ""
    session.naming_queue_entered = ""
    session.naming_typed_letters = 0


def _read_screen_kind_sync(image_bytes: bytes, operator_id: str | None) -> str:
    """Classify screenshot: dialogue, name_entry, or other."""
    import base64
    import json

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Pokemon FireRed/LeafGreen screenshot. Classify the screen:\n"
                        "- dialogue: story/dialog text box at bottom (no letter grid)\n"
                        "- name_entry: letter grid for trainer or rival name\n"
                        "- other: overworld, battle, menu, title, etc.\n"
                        'Reply JSON only: {"screen": "dialogue"|"name_entry"|"other"}'
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
                    },
                },
            ],
        }
    ]
    try:
        raw = _vision_complete(messages, operator_id, purpose="probe")
        data = parse_llm_json_dict(raw, fallback_keys=("screen",))
        if not isinstance(data, dict):
            return "other"
        kind = str(data.get("screen") or "other").strip().lower()
        if kind in ("dialogue", "name_entry", "other"):
            return kind
        return "other"
    except Exception as exc:  # noqa: BLE001
        log.debug("screen kind read failed: %s", exc)
        return "other"


async def _read_screen_kind(image_bytes: bytes, operator_id: str | None) -> str:
    return await asyncio.to_thread(_read_screen_kind_sync, image_bytes, operator_id)


def _likely_name_screen(session: NeuroSession, profile_id: str) -> bool:
    if _next_name_to_spell(session, profile_id) is None:
        return False
    if session.naming_target:
        return True
    gp = (session.goal_progress or "").lower()
    if any(k in gp for k in ("name", "maya", "gary", "letter", "grid")):
        return True
    for entry in session.turn_history[-6:]:
        text = str(entry.get("goal_progress") or "").lower()
        if any(k in text for k in ("name", "maya", "gary", "letter", "grid")):
            return True
    return False


def _read_dialogue_trap_sync(image_bytes: bytes, operator_id: str | None) -> str | None:
    """Detect repeat-interact traps (NES, NPC) from dialogue text. None = no trap."""
    import base64
    import json

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Pokemon FireRed/LeafGreen screenshot. Is there a dialogue text box?\n"
                        "If yes, does it mention playing with NES/SNES/game console, or is the "
                        "player stuck re-interacting with the same object/NPC in a bedroom?\n"
                        'Reply JSON only: {"trap": "none"|"nes_repeat"|"dialogue_repeat", '
                        '"has_text_box": true/false}'
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
                    },
                },
            ],
        }
    ]
    try:
        raw = _vision_complete(messages, operator_id, purpose="probe")
        data = parse_llm_json_dict(raw, fallback_keys=("trap", "has_text_box"))
        if not isinstance(data, dict):
            return None
        trap = str(data.get("trap") or "none").strip().lower()
        if trap in ("nes_repeat", "dialogue_repeat"):
            return trap
        return None
    except Exception as exc:  # noqa: BLE001
        log.debug("dialogue trap read failed: %s", exc)
        return None


async def _read_dialogue_trap(image_bytes: bytes, operator_id: str | None) -> str | None:
    return await asyncio.to_thread(_read_dialogue_trap_sync, image_bytes, operator_id)


def _should_force_walkaway(session: NeuroSession, *, naming_active: bool) -> bool:
    if naming_active:
        return False
    recent = _recent_actions(session, 6)
    a_count = sum(1 for a in recent if a in ("press_a", "advance_dialog"))
    if session.unchanged_force_streak >= 2 and a_count >= 1:
        return True
    if _a_press_streak(session) >= 2:
        return True
    if a_count >= 3 and len(recent) >= 4:
        return True
    return False


def _pick_walkaway(session: NeuroSession, allowed: set[str]) -> str | None:
    arrows = _escape_arrows(allowed)
    if not arrows:
        return None
    recent = _recent_actions(session, 4)
    for arrow in arrows:
        if arrow not in recent[-2:]:
            return arrow
    return arrows[0]


def _next_name_to_spell(session: NeuroSession, profile_id: str) -> str | None:
    try:
        profile = load_profile(profile_id)
    except Exception:  # noqa: BLE001
        return None
    pb = profile.playbook
    spelled = set(getattr(session, "names_spelled", None) or [])
    for key in ("trainer_name", "rival_name"):
        name = str(pb.get(key) or "").strip().upper()
        if name and name not in spelled:
            return name
    return None


def _read_entered_name_sync(image_bytes: bytes, operator_id: str | None) -> str | None:
    """Read the name field on a FRLG name-entry screen. None = not on that screen."""
    import base64
    import json

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Is this a Pokemon FireRed/LeafGreen NAME ENTRY screen with a letter grid?\n"
                        "If yes, read ONLY the letters already entered in the name box (e.g. MAYA, AMMM, empty).\n"
                        "If the box is empty, use an empty string — never the word EMPTY.\n"
                        "Reply with JSON only:\n"
                        '{"on_name_screen": true/false, "entered": "LETTERS_OR_EMPTY"}'
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
                    },
                },
            ],
        }
    ]
    try:
        raw = _vision_complete(messages, operator_id, purpose="probe")
        data = parse_llm_json_dict(
            raw,
            fallback_keys=("on_name_screen", "entered", "screen"),
        )
        if isinstance(data, dict) and data.get("on_name_screen"):
            return normalize_entered_name(str(data.get("entered") or ""))
        prose = parse_entered_from_prose(raw)
        if prose or re.search(r"name entry|name screen|letter grid|YOUR NAME", raw or "", re.I):
            return prose
        return None
    except Exception as exc:  # noqa: BLE001
        log.debug("read entered name failed: %s", exc)
        return None


async def _read_entered_name(image_bytes: bytes, operator_id: str | None) -> str | None:
    return await asyncio.to_thread(_read_entered_name_sync, image_bytes, operator_id)


async def _resolve_naming_target(
    session: NeuroSession,
    profile_id: str,
    image_bytes: bytes | None,
    *,
    screen_kind: str,
) -> str | None:
    """Return target name when on name-entry screen (vision drives all actions)."""
    if not image_bytes:
        return session.naming_target or None

    target = (session.naming_target or _next_name_to_spell(session, profile_id) or "").upper()
    if not target:
        return None

    on_name_screen = (
        screen_kind == "name_entry"
        or bool(session.naming_target)
        or _likely_name_screen(session, profile_id)
    )
    if not on_name_screen:
        entered_probe = await _read_entered_name(image_bytes, session.operator_id)
        if entered_probe is None:
            return None

    # Re-enter naming if we're still on the grid but the name isn't actually complete.
    if target in session.names_spelled and screen_kind == "name_entry":
        from services.game.trace import game_trace

        session.names_spelled = [n for n in session.names_spelled if n != target]
        session.naming_typed_letters = 0
        game_trace(
            session.operator_id,
            "naming.reopen",
            level="warning",
            target=target,
            reason="still_on_name_screen",
        )

    session.naming_queue.clear()
    if session.naming_target != target:
        session.naming_typed_letters = 0
    session.naming_target = target
    return target


async def _run_naming_vision_turn(
    session: NeuroSession,
    *,
    naming_target: str,
    image_bytes: bytes,
    allowed: set[str],
    goal: str,
    autonomous: bool,
) -> None:
    """LLM reads the screenshot and picks one naming button. No playbook, no guards."""
    from services.game.naming_vision import pick_naming_action_sync
    from services.game.trace import game_trace

    recent = _recent_actions(session, 4)
    picked = await asyncio.to_thread(
        pick_naming_action_sync,
        image_bytes,
        target=naming_target,
        operator_id=session.operator_id,
        allowed=allowed,
        recent_actions=recent,
        typed_letters=session.naming_typed_letters,
    )
    action = str(picked.get("action") or "press_down")
    entered = str(picked.get("entered") or "")
    cursor_on = str(picked.get("cursor_on") or "").strip().upper()
    if action not in allowed:
        action = next(iter(allowed))

    if action == "press_a" and cursor_on not in ("OK", "BACK", "BLANK", ""):
        session.naming_typed_letters += 1
    if entered and len(entered) > len(session.naming_known_entered):
        session.naming_known_entered = entered

    if (
        picked.get("done_explicit")
        and picked.get("entered_json") == naming_target
        and action == "press_a"
        and cursor_on == "OK"
        and session.naming_typed_letters >= len(naming_target)
    ):
        if naming_target not in session.names_spelled:
            session.names_spelled.append(naming_target)
        game_trace(session.operator_id, "naming.verified", name=naming_target, via="vision")
        _clear_naming(session)

    goal_progress = (
        f"Name {naming_target}: {action} "
        f"(box={entered!r}, cursor={cursor_on!r})"
    )
    game_trace(
        session.operator_id,
        "naming.vision",
        target=naming_target,
        entered=entered,
        cursor_on=cursor_on,
        action=action,
        done=bool(picked.get("done")),
        raw=(picked.get("raw") or "")[:120],
    )
    await _complete_turn(
        session,
        action=action,
        say="",
        goal_progress=goal_progress,
        goal_reached=False,
        goal=goal,
        autonomous=autonomous,
    )


def _guard_action(action: str, session: NeuroSession, allowed: set[str]) -> tuple[str, str | None]:
    """Block A-spam, nudge movement, and escape interact loops on unchanged screens."""
    naming_active = bool(session.naming_queue or session.naming_target or session.naming_pending_verify)
    if naming_active:
        return action, None

    recent = _recent_actions(session, 6)

    if _should_force_walkaway(session, naming_active=False):
        walk = _pick_walkaway(session, allowed)
        if walk and action in ("press_a", "advance_dialog", "wait"):
            return walk, "stuck_interact_loop"

    if action == "wait" and recent and recent[-1] == "wait":
        if "press_down" in allowed:
            return "press_down", "anti_wait_spam"
        if "advance_dialog" in allowed:
            return "advance_dialog", "anti_wait_spam"

    if (
        action == "press_a"
        and "advance_dialog" in allowed
        and not naming_active
        and session.unchanged_force_streak >= 1
        and recent and recent[-1] in ("press_a", "advance_dialog")
    ):
        return "advance_dialog", "dialog_burst"

    if not naming_active and action == "press_a" and recent and recent[-1] == "press_a":
        for alt in _escape_arrows(allowed):
            return alt, "anti_a_spam"

    if not naming_active and action == "press_a" and _a_press_streak(session) >= 2:
        walk = _pick_walkaway(session, allowed)
        if walk:
            return walk, "a_streak_escape"

    if not naming_active and action == "advance_dialog" and _a_press_streak(session) >= 3:
        walk = _pick_walkaway(session, allowed)
        if walk:
            return walk, "dialog_streak_escape"

    arrows = [a for a in recent if a.startswith("press_") and a != "press_a"]
    if (
        not naming_active
        and len(arrows) >= 3
        and not any(a in arrows for a in ("press_left", "press_right"))
        and action in ("press_up", "press_down")
    ):
        if "press_right" in allowed:
            return "press_right", "need_horizontal"
        if "press_left" in allowed:
            return "press_left", "need_horizontal"

    return action, None


async def _complete_turn(
    session: NeuroSession,
    *,
    action: str,
    say: str,
    goal_progress: str,
    goal_reached: bool,
    goal: str,
    autonomous: bool,
    action_data: dict[str, Any] | None = None,
) -> None:
    from services.game.trace import game_trace

    game_trace(
        session.operator_id,
        "vision.turn",
        action=action,
        say_len=len(say),
        goal_progress=(goal_progress[:120] if goal_progress else ""),
        turn=session.turn_count + 1,
    )

    if say:
        speak_game_line(say, operator_id=session.operator_id)
        emit_game_chat_line(
            say,
            operator_id=session.operator_id,
            action=action,
            turn=session.turn_count + 1,
        )

    log.info(
        "game turn action=%s say_len=%s goal_progress=%s",
        action,
        len(say),
        goal_progress[:80] if goal_progress else "",
    )

    session.record_turn(
        action=action,
        say=say,
        goal_progress=goal_progress,
        goal_reached=goal_reached,
    )

    try:
        from services.voice.hub import hub

        hub.broadcast(
            {
                "type": "game.turn",
                "operator_id": session.operator_id,
                "session_id": session.session_id,
                "action": action,
                "say": say,
                "goal": goal,
                "goal_progress": goal_progress,
                "goal_reached": goal_reached,
                "turn": session.turn_count,
                "autonomous": session.autonomous,
            }
        )
    except Exception:  # noqa: BLE001
        pass

    await session.send_action(action, action_data or {})

    if goal_reached and session._send is not None:
        try:
            from services.game.neuro_server import game_hub

            game_hub.on_goal_reached(session.operator_id)
        except Exception:  # noqa: BLE001
            pass
        await session._send(
            {
                "command": "session/update",
                "game": session.game_name,
                "data": {
                    "goal_reached": True,
                    "goal": goal,
                    "say": say,
                    "goal_progress": goal_progress,
                    "turn": session.turn_count,
                },
            }
        )


def _parse_turn_json(raw: str, allowed: set[str]) -> dict[str, Any]:
    data = parse_llm_json_dict(
        raw,
        fallback_keys=("action", "say", "goal_reached", "goal_progress", "data"),
    )
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")

    action, say_extra = _recover_action(data, allowed, raw or "")
    if not action:
        bad = str(data.get("action") or "").strip()
        raise ValueError(f"action {bad!r} not in {sorted(allowed)}")

    say = str(data.get("say") or "").strip()
    if not say and say_extra:
        say = say_extra
    say = prepare_game_say(say)

    return {
        "action": action,
        "data": data.get("data") if isinstance(data.get("data"), dict) else {},
        "say": say,
        "goal_reached": bool(data.get("goal_reached", False)),
        "goal_progress": str(data.get("goal_progress") or "").strip(),
    }


def _vision_policy(profile_id: str | None) -> dict[str, Any]:
    """Per-profile vision LLM options (turn_policy.vision_* keys)."""
    try:
        profile = load_profile(profile_id or "pokemon_gba")
        policy = profile.turn_policy
    except Exception:  # noqa: BLE001
        policy = {}
    thinking = bool(policy.get("vision_thinking", False))
    max_tokens = int(policy.get("vision_max_tokens") or (1200 if thinking else 400))
    effort = str(policy.get("vision_reasoning_effort") or ("on" if thinking else "off")).strip().lower()
    think_prefix = str(policy.get("vision_think_prefix") or "").strip()
    timeout_s = float(policy.get("vision_timeout_s") or (90.0 if thinking else 55.0))
    return {
        "enable_thinking": thinking,
        "max_tokens": max_tokens,
        "reasoning_effort": normalize_lmstudio_reasoning_effort(effort, enabled=thinking),
        "think_prefix": think_prefix,
        "timeout_s": timeout_s,
    }


def vision_timeout_s(profile_id: str | None) -> float:
    return float(_vision_policy(profile_id).get("timeout_s") or 55.0)


_THINK_BLOCK_RE = re.compile(r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>", re.I)
_THINK_OPEN_RE = re.compile(r"<\s*think\s*>", re.I)
_THINK_CLOSE_RE = re.compile(r"<\s*/\s*think\s*>", re.I)
_GEMMA_CHANNEL_THOUGHT_RE = re.compile(
    r"<\|channel\|>thought[\s\S]*?<channel\|>",
    re.I,
)


def _strip_thinking_content(text: str) -> str:
    """Remove hidden reasoning blocks (Qwen, Gemma-4) so JSON parsing still works."""
    body = (text or "").strip()
    if not body:
        return ""
    body = _GEMMA_CHANNEL_THOUGHT_RE.sub("", body)
    body = _THINK_BLOCK_RE.sub("", body)
    body = _THINK_OPEN_RE.sub("", body)
    body = _THINK_CLOSE_RE.sub("", body)
    # Unclosed Gemma thought prefix
    if body.lower().startswith("<|channel|>thought"):
        end = body.lower().find("<channel|>")
        if end >= 0:
            body = body[end + len("<channel|>") :]
    return body.strip()


def _resolve_vision_model(operator_id: str | None) -> str | None:
    """Pick a vision-capable model from operator settings."""
    try:
        from services.settings.store import load_effective_settings
        from vision import _vision_model_candidates, model_supports_vision

        settings = load_effective_settings(operator_id)
        reasoning = settings.get("reasoning") if isinstance(settings.get("reasoning"), dict) else {}
        provider = str(reasoning.get("provider", "lm_studio")).lower()
        # Game bridge hits LM Studio directly — use the loaded reasoning model first.
        if provider == "lm_studio":
            lm_model = str(reasoning.get("model") or "").strip()
            if lm_model and model_supports_vision(lm_model, reasoning):
                return lm_model
        imagine = settings.get("imagine") if isinstance(settings.get("imagine"), dict) else {}
        remark_model = str(imagine.get("remark_vision_model") or "").strip()
        if remark_model and model_supports_vision(remark_model, reasoning):
            return remark_model
        for candidate in _vision_model_candidates(None, reasoning):
            if model_supports_vision(candidate, reasoning):
                return candidate
    except Exception:  # noqa: BLE001
        pass
    return None


def _vision_llm_client(operator_id: str | None):
    """Operator-configured LLM client for game vision (never hub.agent.llm)."""
    from services.llm.provider import create_llm_client, get_provider_name

    oid = (operator_id or "").strip()
    if not oid:
        log.warning("game vision: missing operator_id — using global effective settings")
    client = create_llm_client(operator_id=oid or None)
    provider = get_provider_name(operator_id=oid or None)
    log.debug("game vision llm provider=%s operator=%s", provider, oid or "global")
    return client


def _vision_complete(
    messages: list[dict],
    operator_id: str | None,
    *,
    profile_id: str | None = None,
    purpose: str = "turn",
) -> str:
    """Game-loop-only vision LLM call.

    Only ``purpose="turn"`` (main action pick) uses thinking/reasoning_effort from
    the game profile. Probes (name read, trap detect) always use ``none``.
    Voice chat and other subsystems never call this — they use the default LLM path.
    """
    from services.game.trace import game_trace

    policy = _vision_policy(profile_id)
    enable_thinking = bool(policy.get("enable_thinking")) if purpose == "turn" else False
    max_tokens = int(policy.get("max_tokens") or 400)
    if purpose in ("probe", "naming"):
        max_tokens = min(max_tokens, 384)
    reasoning_effort = normalize_lmstudio_reasoning_effort(
        policy.get("reasoning_effort") if enable_thinking else "off",
        enabled=enable_thinking,
    )

    client = _vision_llm_client(operator_id)
    model = _resolve_vision_model(operator_id)
    resp = client.complete(
        messages,
        max_tokens=max_tokens,
        model=model,
        enable_thinking=enable_thinking,
        reasoning_effort=reasoning_effort,
    )
    from services.game.trace import game_trace

    if purpose == "turn":
        rc = getattr(resp, "reasoning_content", "") or ""
        game_trace(
            operator_id or "unknown",
            "vision.llm_result",
            reasoning_effort=reasoning_effort,
            reasoning_chars=len(rc),
            content_chars=len(resp.content or ""),
            model=model or "",
        )
    elif purpose in ("probe", "naming"):
        picked = _pick_game_llm_text(resp, purpose=purpose)
        game_trace(
            operator_id or "unknown",
            "naming.llm_raw",
            purpose=purpose,
            chars=len(picked or ""),
            preview=(picked or "")[:160],
            model=model or "",
        )
    return _pick_game_llm_text(resp, purpose=purpose)


def _recent_history_block(session: NeuroSession) -> str:
    if not session.turn_history:
        return ""
    lines = []
    for entry in session.turn_history[-5:]:
        said = str(entry.get("say") or "").strip()
        if not said:
            continue
        lines.append(f"Turn {entry['turn']}: {said[:120]} [{entry.get('goal_progress', '')}]")
    return "Recent turns:\n" + "\n".join(lines)


async def run_force(session: NeuroSession, force: dict[str, Any]) -> None:
    """Process actions/force: vision pick + TTS narration + goal check."""
    from services.game.trace import game_trace

    action_names = list(force.get("action_names") or [])
    if not action_names:
        log.warning("force with no action_names")
        return

    allowed = set(action_names)
    goal = str(force.get("goal") or session.goal or "").strip()
    autonomous = bool(force.get("autonomous", session.autonomous))
    if goal and not session.goal:
        session.goal = goal
    if autonomous:
        session.autonomous = True

    profile_id = session.profile_id or "pokemon_gba"

    frame_ref = force.get("frame_ref")
    image_b64 = force.get("image")
    image_bytes: bytes | None = None
    if image_b64:
        import base64

        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception as exc:  # noqa: BLE001
            log.warning("bad inline image: %s", exc)
    elif frame_ref:
        image_bytes = resolve_frame_bytes(str(frame_ref))

    screen_kind = "other"
    if image_bytes:
        screen_kind = await _read_screen_kind(image_bytes, session.operator_id)
        if screen_kind == "dialogue" and "advance_dialog" in allowed:
            if session.naming_active:
                game_trace(
                    session.operator_id,
                    "naming.aborted",
                    level="warning",
                    reason="dialogue_screen",
                )
                _clear_naming(session)
            await _complete_turn(
                session,
                action="advance_dialog",
                say="",
                goal_progress="Advancing dialogue",
                goal_reached=False,
                goal=goal,
                autonomous=autonomous,
            )
            return
        if session.naming_target and screen_kind not in ("name_entry", "other"):
            probe = await _read_entered_name(image_bytes, session.operator_id)
            if probe is None:
                game_trace(
                    session.operator_id,
                    "naming.aborted",
                    level="warning",
                    reason=f"screen_{screen_kind}",
                )
                _clear_naming(session)

    naming_target = await _resolve_naming_target(
        session,
        profile_id,
        image_bytes,
        screen_kind=screen_kind,
    )
    _update_force_streak(session, image_bytes)

    if naming_target and image_bytes:
        await _run_naming_vision_turn(
            session,
            naming_target=naming_target,
            image_bytes=image_bytes,
            allowed=allowed,
            goal=goal,
            autonomous=autonomous,
        )
        return

    if screen_kind == "name_entry" and image_bytes:
        pending = _next_name_to_spell(session, profile_id)
        if pending:
            session.naming_target = pending.upper()
            await _run_naming_vision_turn(
                session,
                naming_target=pending.upper(),
                image_bytes=image_bytes,
                allowed=allowed,
                goal=goal,
                autonomous=autonomous,
            )
            return

    # Fast path: vision trap read when likely stuck on NES / repeat dialogue
    if image_bytes and _should_force_walkaway(session, naming_active=False):
        trap = await _read_dialogue_trap(image_bytes, session.operator_id)
        if trap:
            walk = _pick_walkaway(session, allowed) or "press_down"
            if walk in allowed:
                game_trace(
                    session.operator_id,
                    "vision.trap_escape",
                    level="warning",
                    trap=trap,
                    action=walk,
                    unchanged_streak=session.unchanged_force_streak,
                )
                await _complete_turn(
                    session,
                    action=walk,
                    say="",
                    goal_progress=f"Leaving stuck interaction ({trap})",
                    goal_reached=False,
                    goal=goal,
                    autonomous=autonomous,
                )
                return

    # Block slow general-vision turns while a name still needs spelling.
    if image_bytes and _next_name_to_spell(session, profile_id) and _likely_name_screen(session, profile_id):
        target = _next_name_to_spell(session, profile_id)
        if target:
            session.naming_target = target.upper()
            await _run_naming_vision_turn(
                session,
                naming_target=target.upper(),
                image_bytes=image_bytes,
                allowed=allowed,
                goal=goal,
                autonomous=autonomous,
            )
            return

    state = str(force.get("state") or "")
    query = str(force.get("query") or "Pick the next action.")

    context_parts = [state] if state else []
    if goal or profile_id in ("pokemon_gba", "pokemon_firered", "pokemon_leafgreen"):
        context_parts.append(
            milestone_context(
                goal=goal,
                goal_progress=session.goal_progress or "",
                turn=session.turn_count + 1,
            )
        )
    if goal:
        context_parts.append(f"GOAL: {goal}")
    if session.goal_progress:
        context_parts.append(f"Last progress: {session.goal_progress}")
    hist = _recent_history_block(session)
    if hist:
        context_parts.append(hist)
    context_parts.append(f"Turn #{session.turn_count + 1}")
    if autonomous:
        context_parts.append(
            "Act every turn — use ALL four arrows (including left/right). "
            "On name grids: move cursor first, then press_a once. Never mash A."
        )
    recent = _recent_actions(session, 4)
    if recent.count("press_a") >= 2:
        context_parts.append(
            "WARNING: You have been pressing A repeatedly. STOP. Use press_left or press_right "
            "to move sideways on the letter grid, or arrows to walk on overworld. "
            "If stuck in a minigame or wrong menu, press_b to exit — do not mash A."
        )
    actions_line = "Allowed actions: " + ", ".join(sorted(allowed))
    context_parts.append(actions_line)
    user_text = "\n\n".join(context_parts) + f"\n\n{query}"

    vision_policy = _vision_policy(profile_id)
    resolved_model = _resolve_vision_model(session.operator_id)
    if vision_policy.get("enable_thinking"):
        prefix = think_prefix_for_model(
            resolved_model,
            str(vision_policy.get("think_prefix") or ""),
        )
        if prefix and not user_text.startswith(prefix):
            user_text = f"{prefix}\n{user_text}"

    system = _game_play_prompt(
        goal=goal,
        autonomous=autonomous or bool(goal),
        allowed_actions=action_names,
        profile_guide=_load_profile_guide(profile_id),
        vision_thinking=bool(vision_policy.get("enable_thinking")),
    )
    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    if image_bytes:
        import base64

        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
                },
            }
        )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    action = "wait"
    say = ""
    goal_reached = False
    goal_progress = ""
    raw = ""

    try:
        if vision_policy.get("enable_thinking"):
            game_trace(session.operator_id, "vision.thinking", profile=profile_id)
        raw = await asyncio.to_thread(
            _vision_complete,
            messages,
            session.operator_id,
            profile_id=profile_id,
            purpose="turn",
        )
        parsed = _parse_turn_json(raw, allowed)
        action = parsed["action"]
        say = prepare_game_say(parsed["say"])
        goal_reached = parsed["goal_reached"]
        goal_progress = parsed["goal_progress"]
    except Exception as exc:  # noqa: BLE001
        log.warning("vision force failed: %s (raw=%r)", exc, raw[:240] if raw else "")
        game_trace(
            session.operator_id,
            "vision.parse_failed",
            level="warning",
            error=str(exc)[:300],
            raw=(raw[:200] if raw else ""),
        )
        say = ""
        inferred = _infer_action_from_raw(raw, allowed)
        if inferred:
            action = inferred
        elif "press_down" in allowed:
            action = "press_down"
        else:
            action = "wait" if "wait" in allowed else next(iter(allowed))

    guarded, guard_reason = _guard_action(action, session, allowed)
    if guard_reason and guarded != action:
        game_trace(
            session.operator_id,
            "vision.action_guard",
            level="warning",
            from_action=action,
            to_action=guarded,
            reason=guard_reason,
        )
        action = guarded

    await _complete_turn(
        session,
        action=action,
        say=say,
        goal_progress=goal_progress,
        goal_reached=goal_reached,
        goal=goal,
        autonomous=autonomous,
    )
