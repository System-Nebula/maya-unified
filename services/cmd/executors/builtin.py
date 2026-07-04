"""Built-in cmd executors."""

from __future__ import annotations

from services.cmd.models import CmdContext, CmdResult, CmdSurface
from services.cmd.registry import registry


def exec_help(ctx: CmdContext, _args: dict) -> CmdResult:
    surface = ctx.surface
    cmds = registry.list_cmds(surface=surface)
    if not cmds:
        return CmdResult(ok=True, text="No cmds are registered for this surface yet.")
    lines = ["Available cmds:"]
    current_category = ""
    for cmd in cmds:
        if cmd.category != current_category:
            current_category = cmd.category
            lines.append(f"\n{current_category}")
        aliases = f" ({', '.join('/' + a for a in cmd.aliases)})" if cmd.aliases else ""
        lines.append(f"  /{cmd.name}{aliases} — {cmd.description}")
    return CmdResult(ok=True, text="\n".join(lines).strip())


def exec_status(ctx: CmdContext, _args: dict) -> CmdResult:
    from services.voice.hub import hub

    oid = ctx.operator_id
    snap = hub.agent_capabilities(oid or None)
    llm = hub.llm_status(oid or None)
    caps = snap.get("capabilities") or {}
    lines = [
        f"Agent ready: {hub.ready}",
        f"Status: {hub.status}",
        f"LLM ok: {llm.get('ok', False)}",
        f"LLM model: {llm.get('model') or '—'}",
        f"Text chat: {caps.get('text_chat', False)}",
        f"Voice session: {caps.get('voice_session', False)}",
        f"TTS preview: {caps.get('tts_preview', False)}",
    ]
    if hub.last_error:
        lines.append(f"Last error: {hub.last_error}")
    return CmdResult(ok=True, text="\n".join(lines))
