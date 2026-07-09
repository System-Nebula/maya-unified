"""Randy-style Neuro client round-trip against game hub (no LLM)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.neuro_server import game_hub  # noqa: E402


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_hub_handle_startup_and_register():
    ws = _FakeWebSocket()
    conn = await game_hub.attach("op-randy", ws, profile_id="pokemon_gba")

    raw = json.dumps({"command": "startup", "game": "Randy Test"})
    result = await game_hub.handle_message("op-randy", raw)
    assert result["ok"]
    assert conn.neuro.game_name == "Randy Test"

    reg = json.dumps(
        {
            "command": "actions/register",
            "game": "Randy Test",
            "data": {"actions": [{"name": "press_a", "description": "go"}]},
        }
    )
    reg_result = await game_hub.handle_message("op-randy", reg)
    assert reg_result["ok"]
    assert "press_a" in conn.neuro.actions

    await game_hub.detach("op-randy")


@pytest.mark.asyncio
async def test_hub_force_triggers_agent_loop_mock():
    ws = _FakeWebSocket()
    await game_hub.attach("op-randy2", ws, profile_id="pokemon_gba")
    await game_hub.handle_message(
        "op-randy2",
        json.dumps({"command": "startup", "game": "Randy Test"}),
    )
    await game_hub.handle_message(
        "op-randy2",
        json.dumps(
            {
                "command": "actions/register",
                "game": "Randy Test",
                "data": {"actions": [{"name": "wait", "description": "pause"}]},
            }
        ),
    )

    conn = game_hub.get("op-randy2")
    assert conn is not None

    async def fake_run_force(session, force):
        await session.send_action("wait", {"ms": 100})

    async def send_json(payload: dict) -> None:
        await ws.send_text(json.dumps(payload))

    conn.neuro.bind(send_json, fake_run_force)

    result = await game_hub.handle_message(
        "op-randy2",
        json.dumps(
            {
                "command": "actions/force",
                "game": "Randy Test",
                "data": {"action_names": ["wait"], "query": "pick"},
            }
        ),
    )
    assert result and result.get("ok"), result

    assert ws.sent, "expected websocket messages"
    payloads = [json.loads(s) for s in ws.sent]
    assert any(p.get("command") == "action" for p in payloads)
    await game_hub.detach("op-randy2")
