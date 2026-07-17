"""Command capability policy (SEC-003).

Enforced in the central dispatcher so dashboard, chat, Discord, and other
surfaces share one gate. Route-level auth still binds identity; this module
decides whether that principal may run the command/action.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.cmd.models import CmdContext, CmdDefinition, ParsedCmd

log = logging.getLogger("maya-unified.cmd.capabilities")

COMMAND_BASIC = "command.basic"
IMAGINE_SUBMIT = "imagine.submit"
RESEARCH_RUN = "research.run"
BLENDER_INSPECT = "blender.inspect"
BLENDER_RENDER = "blender.render"
BLENDER_EXECUTE_CODE = "blender.execute_code"
GAME_CONTROL = "game.control"

_OPERATOR_CAPS = frozenset(
    {
        COMMAND_BASIC,
        IMAGINE_SUBMIT,
        RESEARCH_RUN,
        BLENDER_INSPECT,
        BLENDER_RENDER,
        GAME_CONTROL,
    }
)


def blender_execute_code_enabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return str(env.get("MAYA_BLENDER_EXECUTE_CODE", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def resolve_operator_role(ctx: "CmdContext") -> str:
    """Least-privilege default when role is unknown: ordinary operator."""
    role = str((ctx.metadata or {}).get("operator_role") or "").strip().lower()
    if role in {"admin", "operator"}:
        return role
    return "operator"


def granted_capabilities(
    role: str,
    *,
    environ: dict[str, str] | None = None,
) -> frozenset[str]:
    caps = set(_OPERATOR_CAPS)
    if role == "admin" and blender_execute_code_enabled(environ):
        caps.add(BLENDER_EXECUTE_CODE)
    return frozenset(caps)


def _blend_action_capability(action: str) -> str:
    a = (action or "summary").strip().lower()
    if a == "render":
        return BLENDER_RENDER
    if a == "code":
        return BLENDER_EXECUTE_CODE
    return BLENDER_INSPECT


def required_capabilities(
    cmd: "CmdDefinition",
    parsed: "ParsedCmd",
    ctx: "CmdContext",
) -> frozenset[str]:
    required: set[str] = set(cmd.permissions) if cmd.permissions else {COMMAND_BASIC}
    if cmd.id == "blend":
        from services.cmd.executors.blender import _parse_blend_args

        action = str(_parse_blend_args(ctx, parsed.args).get("action") or "summary")
        required.add(_blend_action_capability(action))
    return frozenset(required)


def permission_denied_message(missing: set[str]) -> str:
    caps = ", ".join(sorted(missing))
    if BLENDER_EXECUTE_CODE in missing:
        return (
            "permission denied: blender.execute_code requires admin role and "
            "MAYA_BLENDER_EXECUTE_CODE=1"
        )
    return f"permission denied: missing {caps}"


def check_cmd_permissions(
    cmd: "CmdDefinition",
    parsed: "ParsedCmd",
    ctx: "CmdContext",
    *,
    environ: dict[str, str] | None = None,
) -> str | None:
    """Return an error string when the principal lacks required capabilities."""
    role = resolve_operator_role(ctx)
    granted = granted_capabilities(role, environ=environ)
    required = required_capabilities(cmd, parsed, ctx)
    missing = set(required) - set(granted)
    if not missing:
        return None

    if BLENDER_EXECUTE_CODE in missing:
        log.warning(
            "blender.execute_code denied operator_id=%s role=%s corr_id=%s enabled=%s",
            ctx.operator_id,
            role,
            (ctx.metadata or {}).get("corr_id"),
            blender_execute_code_enabled(environ),
        )
    return permission_denied_message(missing)


def assert_blender_execute_allowed(ctx: "CmdContext") -> str | None:
    """Defense-in-depth gate inside the blender executor."""
    role = resolve_operator_role(ctx)
    if role != "admin" or not blender_execute_code_enabled():
        log.warning(
            "blender.execute_code blocked operator_id=%s role=%s corr_id=%s",
            ctx.operator_id,
            role,
            (ctx.metadata or {}).get("corr_id"),
        )
        return permission_denied_message({BLENDER_EXECUTE_CODE})
    log.info(
        "blender.execute_code allowed operator_id=%s corr_id=%s",
        ctx.operator_id,
        (ctx.metadata or {}).get("corr_id"),
    )
    return None
