"""Discord integration — voice runs via qwen3 DiscordManager inside VoiceAgent."""

from __future__ import annotations

import logging
import os

from services.settings.store import load_settings

log = logging.getLogger("maya-unified.discord")


def apply_discord_env(settings: dict) -> None:
    """Mirror unified discord settings into os.environ for qwen3 CONFIG."""
    disc = settings.get("discord", {})
    token = str(disc.get("token") or "").strip()
    enabled = bool(token) or bool(disc.get("enabled"))
    os.environ["VA_DISCORD_ENABLED"] = "1" if enabled else "0"
    if token:
        os.environ["VA_DISCORD_TOKEN"] = token
        if disc.get("guild_id"):
            os.environ["VA_DISCORD_GUILD_ID"] = str(disc["guild_id"])
        if disc.get("auto_reply") is not None:
            os.environ["VA_DISCORD_AUTO_REPLY"] = "1" if disc.get("auto_reply") else "0"
    if disc.get("comfyui_url"):
        os.environ["COMFYUI_API_URL"] = str(disc["comfyui_url"])


def start_discord_extensions(hub) -> None:
    """Log Discord readiness after the voice agent finishes loading."""
    agent = hub.agent
    if agent is not None and getattr(agent, "discord", None) is not None:
        log.info("discord tools loaded — bot warms on first join/play")
        return
    disc = load_settings().get("discord", {})
    if str(disc.get("token") or "").strip():
        log.warning(
            "discord token is set but bot tools did not load — save Discord settings again or restart the server"
        )
    else:
        log.info("discord not configured — add a bot token in Settings → Discord")
