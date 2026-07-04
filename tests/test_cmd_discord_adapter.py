"""Discord adapter tests for cmd_registry."""

from __future__ import annotations

import pytest

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.discord_adapter import cmd_to_discord_spec, list_discord_cmd_specs
from services.cmd.models import CmdSurface
from services.cmd.registry import registry


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    from services.cmd import bootstrap

    monkeypatch.setattr(bootstrap, "_bootstrapped", False)
    registry._by_id.clear()
    registry._alias_index.clear()
    ensure_cmds_registered()


def test_list_discord_cmd_specs_includes_imagine():
    specs = list_discord_cmd_specs()
    names = {spec.name for spec in specs}
    assert "help" in names
    assert "status" in names
    assert "imagine" in names


def test_imagine_spec_has_prompt_option():
    cmd = registry.get("imagine")
    assert cmd is not None
    spec = cmd_to_discord_spec(cmd)
    assert spec.cmd_id == "imagine"
    assert any(opt.name == "prompt" and opt.required for opt in spec.options)


def test_surface_gating_excludes_non_discord_cmds():
    from services.cmd.models import CmdDefinition, CmdResult

    registry.register(
        CmdDefinition(
            id="dashboard-only",
            name="dashonly",
            description="Dashboard-only cmd",
            surfaces=[CmdSurface.DASHBOARD],
            executor=lambda _ctx, _args: CmdResult(ok=True, text="ok"),
        )
    )
    names = {spec.name for spec in list_discord_cmd_specs()}
    assert "dashonly" not in names
