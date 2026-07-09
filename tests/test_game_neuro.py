"""Tests for Neuro game session protocol."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.neuro_session import NeuroSession  # noqa: E402


@pytest.mark.asyncio
async def test_startup_register_force_action_result():
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    async def run_force(session: NeuroSession, force: dict) -> None:
        await session.send_action("press_a", {})

    session = NeuroSession(operator_id="op-1", session_id="sess-1")
    session.bind(send, run_force)

    await session.handle({"command": "startup", "game": "Test Game"})
    reg = await session.handle(
        {
            "command": "actions/register",
            "game": "Test Game",
            "data": {
                "actions": [
                    {"name": "press_a", "description": "confirm"},
                ]
            },
        }
    )
    assert reg["ok"]
    assert "press_a" in session.actions

    force = await session.handle(
        {
            "command": "actions/force",
            "game": "Test Game",
            "data": {
                "action_names": ["press_a"],
                "query": "pick",
            },
        }
    )
    assert force["ok"]
    assert session.force_in_progress
    assert any(m.get("command") == "action" for m in sent)

    action_msg = next(m for m in sent if m.get("command") == "action")
    action_id = action_msg["data"]["id"]

    result = await session.handle(
        {
            "command": "action/result",
            "game": "Test Game",
            "data": {"id": action_id, "success": True, "message": "ok"},
        }
    )
    assert result["ok"]
    assert session.force_in_progress is False


@pytest.mark.asyncio
async def test_force_rejected_when_busy():
    session = NeuroSession(operator_id="op-1", session_id="sess-1")
    session.force_in_progress = True
    out = await session.handle(
        {
            "command": "actions/force",
            "game": "G",
            "data": {"action_names": ["a"], "query": "q"},
        }
    )
    assert out["ok"] is False


def test_plan_name_fix_deletes_wrong_name():
    from services.game.naming_playbook import plan_name_fix

    actions = plan_name_fix("AMMMM", "MAYA")
    assert actions[:5] == ["press_b"] * 5
    assert "press_a" in actions
    assert actions.count("press_left") >= 1
    assert actions.count("press_right") >= 1


def test_load_pokemon_profile():
    from services.game.profiles import load_profile

    p = load_profile("pokemon_gba")
    assert p.id == "pokemon_gba"
    assert any(a.name == "press_a" for a in p.actions)
    assert p.input["keymap"]["a"] == "x"
    assert "MAYA" in p.prompt_guide
    assert "GARY" in p.prompt_guide
    assert p.playbook.get("rival_name") == "GARY"
    assert "Eevee" in p.prompt_guide
    assert p.playbook.get("trainer_name") == "MAYA"
    assert p.turn_policy.get("analysis_fps_min") == 0.4
    assert p.turn_policy.get("analysis_fps_max") == 1.0
    assert p.capture.get("poll_fps") == 6


def test_resolve_game_timing_fps():
    from services.game.profiles import load_profile
    from services.game.timing import resolve_game_timing

    profile = load_profile("pokemon_gba")
    timing = resolve_game_timing(profile, {"game": {"poll_fps": 6, "analysis_fps_max": 0.5}})
    assert timing.poll_fps == 6
    assert timing.poll_ms == 166
    assert timing.min_analysis_gap_ms == 2000


def test_turn_pause_includes_tts_buffer():
    from services.game.timing import GameTiming

    timing = GameTiming(poll_fps=8, analysis_fps_min=0.4, analysis_fps_max=1.0)
    short = timing.turn_pause_ms("")
    spoken = timing.turn_pause_ms("Hi.")
    long = timing.turn_pause_ms("A" * 80)
    assert short == 1000
    assert spoken > short
    assert long > spoken

