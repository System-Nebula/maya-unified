"""Translate cmd_registry metadata into Discord app command specs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.models import CmdDefinition, CmdParameter, CmdSurface
from services.cmd.registry import registry


@dataclass
class DiscordCmdOptionSpec:
    name: str
    description: str
    required: bool = False
    choices: list[str] = field(default_factory=list)
    type: str = "string"


@dataclass
class DiscordCmdSpec:
    name: str
    description: str
    options: list[DiscordCmdOptionSpec] = field(default_factory=list)
    cmd_id: str = ""


def _option_spec(param: CmdParameter) -> DiscordCmdOptionSpec:
    return DiscordCmdOptionSpec(
        name=param.name,
        description=param.description or param.name,
        required=param.required,
        choices=list(param.choices),
        type=param.type,
    )


def cmd_to_discord_spec(cmd: CmdDefinition) -> DiscordCmdSpec:
    options = [_option_spec(p) for p in cmd.parameters if p.name != "mode" or p.choices]
    return DiscordCmdSpec(
        name=cmd.name[:32],
        description=(cmd.description or cmd.name)[:100],
        options=options,
        cmd_id=cmd.id,
    )


def list_discord_cmd_specs() -> list[DiscordCmdSpec]:
    ensure_cmds_registered()
    return [cmd_to_discord_spec(cmd) for cmd in registry.list_cmds(surface=CmdSurface.DISCORD)]


def discord_options_to_args(cmd: CmdDefinition, options: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for opt in options or []:
        name = str(opt.get("name") or "")
        if not name:
            continue
        out[name] = opt.get("value")
    for param in cmd.parameters:
        if param.name not in out and param.default is not None:
            out[param.name] = param.default
    return out
