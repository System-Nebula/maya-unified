"""Source-backed Maya Discord bot entrypoint."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import discord
import structlog
from discord.ext import commands
from dotenv import load_dotenv

logger = structlog.get_logger()
_PRESERVE_ENV_KEYS = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_SERVICE_NAME",
)


def _snowflake_id(value: object) -> int | None:
    """Return a Discord snowflake id from an object, or ``None`` if absent."""
    snowflake = getattr(value, "id", None)
    return snowflake if isinstance(snowflake, int) else None


def _current_trace_fields() -> dict[str, str]:
    """Return active OTel ids for structured logs without requiring tracing."""
    try:
        from observability import current_span_id, current_trace_id
    except Exception:
        return {}

    fields: dict[str, str] = {}
    trace_id = current_trace_id()
    span_id = current_span_id()
    if trace_id:
        fields["trace_id"] = trace_id
    if span_id:
        fields["span_id"] = span_id
    return fields


def _load_env() -> None:
    """Load local dotenv files without clobbering supervisor-provided OTEL env."""
    preserved = {
        key: value
        for key in _PRESERVE_ENV_KEYS
        if (value := os.environ.get(key)) is not None
    }
    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env")
    load_dotenv(root / "apps" / "maya-bot" / ".env", override=True)
    os.environ.update(preserved)


@dataclass(slots=True)
class MayaSettings:
    allowed_user_ids: set[int] | None = None

    @classmethod
    def from_env(cls) -> "MayaSettings":
        raw_allowed = (os.getenv("ALLOWED_USER_IDS") or "").strip()
        allowed = {
            int(value.strip())
            for value in raw_allowed.split(",")
            if value.strip().isdigit()
        }
        return cls(allowed_user_ids=allowed or None)


class MayaBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.guilds = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )
        self.settings = MayaSettings.from_env()

    async def setup_hook(self) -> None:
        self.tree.on_error = self.on_app_command_error
        for extension in ("maya_bot.cogs.imagine", "maya_bot.cogs.cmd_registry"):
            try:
                await self.load_extension(extension)
            except Exception as exc:
                print(f"failed to load {extension}: {exc}")
        test_guild = os.getenv("TEST_GUILD_ID")
        if test_guild:
            guild = discord.Object(id=int(test_guild))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            # clear global copies so they don't duplicate the guild ones
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            print(f"synced commands to test guild {test_guild}")
        else:
            await self.tree.sync()
            print("global command sync queued (can take up to 1 hour)")

    async def on_ready(self) -> None:
        print(f"Maya logged in as {self.user} (ID: {self.user.id})")

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """Log rich command failure context while sending a generic user reply."""
        cmd = getattr(getattr(interaction, "command", None), "qualified_name", None)
        original = getattr(error, "original", None)
        logger.error(
            "app_command_failed",
            command=cmd,
            interaction_id=_snowflake_id(interaction),
            guild_id=_snowflake_id(getattr(interaction, "guild", None)),
            channel_id=_snowflake_id(getattr(interaction, "channel", None)),
            user_id=_snowflake_id(getattr(interaction, "user", None)),
            error_type=type(error).__name__,
            original_error_type=type(original).__name__ if original else None,
            error=str(error),
            exc_info=error,
            **_current_trace_fields(),
        )
        message = "The command failed. Try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception as exc:
            logger.warning(
                "app_command_error_response_failed",
                command=cmd,
                interaction_id=_snowflake_id(interaction),
                error=str(exc),
                exc_info=exc,
                **_current_trace_fields(),
            )
            return

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        allowed = self.settings.allowed_user_ids
        if not allowed:
            return True
        if interaction.user and interaction.user.id in allowed:
            return True
        if interaction.response.is_done():
            await interaction.followup.send("You are not allowed to use this bot.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "You are not allowed to use this bot.",
                ephemeral=True,
            )
        return False

    @commands.command(name="sync")
    async def sync_commands(self, ctx: commands.Context) -> None:
        """Manually sync slash commands to the current guild."""
        if not ctx.guild:
            await ctx.send("This command only works in servers.")
            return
        guild = discord.Object(id=ctx.guild.id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        await ctx.send(f"Synced {len(synced)} command(s) to this server.")


def main() -> None:
    _load_env()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN environment variable not set")

    try:
        from observability import bootstrap

        bootstrap("maya-bot")
    except Exception as exc:
        print(f"observability setup failed (continuing without tracing): {exc}")

    bot = MayaBot()
    bot.run(token)


if __name__ == "__main__":
    main()
