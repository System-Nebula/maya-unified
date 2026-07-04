"""Runtime patches for qwen3 VoiceAgent + DiscordManager (read-only upstream)."""

from __future__ import annotations

import logging
from typing import Any

from services.discord.channel_resolver import (
    build_channels_hint,
    extract_join_channel_hint,
    list_discord_channels,
    resolve_channel_name,
    resolve_plan_channel_params,
)
from services.discord.fuzzy_channels import resolve_voice_channel_fuzzy
from services.discord.youtube_patch import patch_discord_manager_playback, patch_youtube_tools
from services.settings.store import load_settings

log = logging.getLogger("maya-unified.discord")

_AGENT_PATCHED = "_unified_orchestrator_patch"
_DISCORD_PATCHED = "_unified_fuzzy_voice_patch"


def _channel_aliases() -> dict[str, str]:
    raw = load_settings().get("discord", {}).get("voice_channel_aliases") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def patch_discord_manager(manager: Any) -> None:
    """Fuzzy voice-channel fallback when join runs with a still-wrong name."""
    if manager is None or getattr(manager, _DISCORD_PATCHED, False):
        return

    original = manager._resolve_voice_channel  # noqa: SLF001

    def resolve(guild, channel_name: str):
        channel = original(guild, channel_name)
        if channel is not None:
            return channel
        aliases = _channel_aliases()
        fuzzy = resolve_voice_channel_fuzzy(guild, channel_name, aliases)
        if fuzzy is not None:
            log.info("fuzzy voice channel match: %r -> %r", channel_name, fuzzy.name)
        return fuzzy

    manager._resolve_voice_channel = resolve  # noqa: SLF001
    patch_discord_manager_playback(manager)
    setattr(manager, _DISCORD_PATCHED, True)


def wire_discord_voice_clip(agent: Any) -> None:
    """Ensure Discord bot can synthesize TTS attachments after reload/patch."""
    if agent is None or getattr(agent, "discord", None) is None:
        return
    clip_fn = getattr(agent, "_discord_voice_clip", None)
    if clip_fn is not None:
        agent.discord._voice_clip_fn = clip_fn  # noqa: SLF001
        agent.discord._on_incoming_message = agent._compose_discord_incoming_reply  # noqa: SLF001


def patch_voice_agent(agent: Any) -> None:
    """Orchestrator channel lists + LLM resolve + direct join execution."""
    if agent is None or getattr(agent, _AGENT_PATCHED, False):
        return

    patch_youtube_tools()
    if agent.discord is not None:
        patch_discord_manager(agent.discord)
        wire_discord_voice_clip(agent)

    orig_hint = agent._discord_channels_hint

    def enhanced_channels_hint() -> str:
        if agent.discord is None:
            return orig_hint()
        base = ""
        try:
            base = orig_hint()
        except Exception:  # noqa: BLE001
            pass
        return build_channels_hint(agent.discord, base)

    agent._discord_channels_hint = enhanced_channels_hint

    orig_orchestrate = agent._llm_orchestrate

    def wrapped_orchestrate(raw_text: str, user_text: str):
        plan = orig_orchestrate(raw_text, user_text)
        if plan is not None:
            resolve_plan_channel_params(agent, plan)
        return plan

    agent._llm_orchestrate = wrapped_orchestrate

    orig_execute = agent._execute_orchestrator_plan

    def wrapped_execute(plan, user_text: str, raw_text: str):
        intent = (getattr(plan, "intent", None) or "").lower()
        if intent == "discord_join_voice" and agent.discord is not None:
            params = plan.params if isinstance(plan.params, dict) else {}
            channel = str(params.get("channel_name") or "").strip()
            if not channel:
                channel = extract_join_channel_hint(
                    getattr(plan, "user_meant", None) or user_text or raw_text
                )
            voice, _ = list_discord_channels(agent.discord)
            resolved = resolve_channel_name(agent.llm, channel, voice, kind="voice")
            if resolved:
                channel = resolved
                params["channel_name"] = resolved
            if channel:
                return agent._discord_tool_reply(
                    "discord_join_voice",
                    {"channel_name": channel},
                    lambda ch=channel: agent.discord.join_voice(ch),
                    ok=lambda r, ch=channel: (
                        f"Joined {r.get('joined', ch)}."
                        if r.get("joined") or r.get("ok", True)
                        else f"Joined {ch}."
                    ),
                    fail=f"I couldn't join {channel}.",
                )
        return orig_execute(plan, user_text, raw_text)

    agent._execute_orchestrator_plan = wrapped_execute
    setattr(agent, _AGENT_PATCHED, True)
    log.info("orchestrator discord channel resolver active")
