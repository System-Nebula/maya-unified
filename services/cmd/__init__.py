"""cmd_registry — resolvable user-facing commands (not agentic tools)."""

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.dispatcher import dispatch_cmd
from services.cmd.models import CmdContext, CmdDefinition, CmdResult, CmdSurface
from services.cmd.parser import parse_cmd_input
from services.cmd.registry import registry

__all__ = [
    "CmdContext",
    "CmdDefinition",
    "CmdResult",
    "CmdSurface",
    "dispatch_cmd",
    "ensure_cmds_registered",
    "parse_cmd_input",
    "registry",
]
