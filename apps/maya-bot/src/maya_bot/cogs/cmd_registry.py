"""Discord cog that registers cmds from cmd_registry."""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog
from discord import app_commands
from discord.ext import commands

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.discord_adapter import discord_options_to_args, list_discord_cmd_specs
from services.cmd.models import CmdSurface
from services.cmd.registry import registry

logger = structlog.get_logger()
_GATEWAY_URL = os.getenv("MAYA_GATEWAY_URL", "http://localhost:8080").rstrip("/")


class CmdRegistryCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _dispatch_to_gateway(
        self,
        *,
        cmd_id: str,
        args: dict[str, Any],
        interaction: app_commands.Interaction,
    ) -> dict[str, Any]:
        payload = {
            "cmd_id": cmd_id,
            "args": args,
            "surface": CmdSurface.DISCORD.value,
            "metadata": {
                "discord_user_id": str(interaction.user.id),
                "discord_channel_id": str(interaction.channel_id or ""),
                "discord_guild_id": str(interaction.guild_id or ""),
                "discord_interaction_id": str(interaction.id),
            },
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{_GATEWAY_URL}/api/cmds/dispatch", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def _run_registered_cmd(
        self,
        interaction: app_commands.Interaction,
        cmd_id: str,
        args: dict[str, Any],
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            result = await self._dispatch_to_gateway(
                cmd_id=cmd_id,
                args=args,
                interaction=interaction,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("cmd_registry_dispatch_failed", cmd_id=cmd_id, error=str(exc))
            await interaction.followup.send(f"Command failed: {exc}", ephemeral=True)
            return
        if not result.get("ok"):
            await interaction.followup.send(result.get("error") or "Command failed.", ephemeral=True)
            return
        text = str(result.get("text") or "Done.")
        await interaction.followup.send(text[:1900])

    @app_commands.command(name="help", description="List available Maya cmds")
    async def help_cmd(self, interaction: app_commands.Interaction) -> None:
        await self._run_registered_cmd(interaction, "help", {})

    @app_commands.command(name="status", description="Show Maya agent and LLM readiness")
    async def status_cmd(self, interaction: app_commands.Interaction) -> None:
        await self._run_registered_cmd(interaction, "status", {})


async def setup(bot: commands.Bot) -> None:
    ensure_cmds_registered()
    specs = list_discord_cmd_specs()
    logger.info("cmd_registry_discord_specs", count=len(specs), names=[s.name for s in specs])
    await bot.add_cog(CmdRegistryCog(bot))
