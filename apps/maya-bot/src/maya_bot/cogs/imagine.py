"""Discord `/imagine` commands backed by Maya's image service."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import discord
import structlog
from discord import app_commands
from discord.ext import commands
from opentelemetry import trace

from maya_image.arena.service import get_arena_service
from maya_image.arena_layout import build_side_by_side
from maya_image.graph import record_image_turn, update_turn_rating
from maya_image.mode_resolver import resolve_generation_mode
from maya_image.providers.comfyui_dispatch import mark_dispatched, store_dispatch_context
from maya_image.service import get_image_service
from maya_image.workflows import ImageWorkflow, resolve_workflow_for_model, workflow_supports_remix
from maya_image.types.image_job import ImageJob, ImageJobInput, ImageJobStatus, ImageMode, ImageReference

try:
    from observability import (
        ActorContext,
        RequestContext,
        context_task,
        current_span_id,
        current_trace_id,
        emit_visibility,
        push_frame,
        set_request_context,
        sync_stack_window,
    )
except ImportError:
    from contextlib import contextmanager

    context_task = asyncio.create_task  # type: ignore[misc,assignment]

    def current_trace_id() -> str | None:
        return None

    def current_span_id() -> str | None:
        return None

    def emit_visibility(*_args, **_kwargs) -> None:
        return None

    def sync_stack_window(_span=None) -> None:
        return None

    @contextmanager
    def push_frame(_frame: str):
        yield

    @contextmanager
    def set_request_context(ctx):
        yield ctx

    class ActorContext:  # noqa: D101
        def __init__(self, *args, **kwargs):
            pass

    class RequestContext:  # noqa: D101
        @classmethod
        def new(cls, *_args, **_kwargs):
            return cls()

if TYPE_CHECKING:
    from maya_bot.main import MayaBot

logger = structlog.get_logger()
_tracer = trace.get_tracer("maya.discord.imagine")

_MODE_CHOICES = [
    app_commands.Choice(name="Generate", value="generate"),
    app_commands.Choice(name="Edit", value="edit"),
    app_commands.Choice(name="Arena", value="arena"),
]

# Maps legacy model choice names (kept for tests importing resolve_provider_key).
_MODEL_PROVIDER_KEYS = {
    "ideogram": "ideogram:4",
    "ideogram-local": "comfyui:graph",
    "zit": "comfyui:graph",
    "krea2": "comfyui:graph",
    "krea-2": "comfyui:graph",
    "gpt-image-2": "fal:gpt-image-2",
    "nano-banana-2": "fal:nano-banana-2",
}
_DEFAULT_PROVIDER_KEY = "ideogram:4"

_GENERATION_TIMEOUT_SEC = 300
_JOB_HARD_DEADLINE_SEC = _GENERATION_TIMEOUT_SEC + 30
_ARENA_MAX_POLLS = _GENERATION_TIMEOUT_SEC // 5
_PROGRESS_EDIT_INTERVAL_SEC = 10.0

_MODEL_CHOICES = [
    app_commands.Choice(name="ZIT / Z-Image Turbo (local ComfyUI)", value="zit"),
    app_commands.Choice(name="Krea 2 Turbo (local ComfyUI)", value="krea2"),
    app_commands.Choice(name="Ideogram 4 (local ComfyUI)", value="ideogram-local"),
    app_commands.Choice(name="Ideogram 4 (hosted)", value="ideogram"),
    app_commands.Choice(name="GPT Image 2", value="gpt-image-2"),
    app_commands.Choice(name="Nano Banana 2", value="nano-banana-2"),
]


def resolve_provider_key(model_value: str | None) -> str:
    """Resolve a /imagine model choice to a service provider key."""
    workflow = resolve_workflow_for_model(model_value, mode="generate")
    return workflow.provider_key or _DEFAULT_PROVIDER_KEY


def resolve_workflow(model_value: str | None, mode: str = "generate") -> ImageWorkflow:
    return resolve_workflow_for_model(model_value, mode=mode)


_REFERENCE_REQUIRED = {ImageMode.EDIT}

_ARENA_COMPOSITE_FILENAME = "arena-composite.png"


@dataclass
class _ArenaBattleState:
    battle_id: str
    request: ImageJobInput
    result: dict
    contender_labels: dict[str, str] = field(default_factory=dict)
    slots: dict[str, ImageJob | None] = field(default_factory=lambda: {"a": None, "b": None})
    slot_paths: dict[str, str | None] = field(default_factory=lambda: {"a": None, "b": None})


class ArenaVoteView(discord.ui.View):
    def __init__(self, *, battle_id: str, enabled: bool = True):
        super().__init__(timeout=None)
        self.battle_id = battle_id
        self.arena = get_arena_service()
        if not enabled:
            for item in self.children:
                item.disabled = True

    async def _submit_vote(self, interaction: discord.Interaction, choice: str) -> None:
        try:
            await asyncio.to_thread(
                self.arena.vote,
                self.battle_id,
                str(interaction.user.id),
                interaction.user.display_name,
                choice,
            )
            if choice in ("a", "b"):
                await asyncio.to_thread(
                    self.arena.record_sentiment,
                    self.battle_id,
                    choice,
                    str(interaction.user.id),
                    interaction.user.display_name,
                    "up",
                )
                await asyncio.to_thread(self.arena.apply_sentiment_elo, self.battle_id, choice, "up")
            await interaction.response.send_message(f"Vote recorded for `{choice.upper()}`", ephemeral=True)
        except Exception as exc:
            logger.warning(
                "arena_vote_failed",
                battle_id=self.battle_id,
                choice=choice,
                error=str(exc),
            )
            message = (
                "Could not record your vote right now (database may be busy). "
                "Try again in a moment, or react 👍/👎 on the contender images."
            )
            if str(exc):
                message = f"{message}\n({exc})"
            await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="A", style=discord.ButtonStyle.primary)
    async def vote_a(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._submit_vote(interaction, "a")

    @discord.ui.button(label="Tie", style=discord.ButtonStyle.secondary)
    async def vote_tie(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._submit_vote(interaction, "tie")

    @discord.ui.button(label="B", style=discord.ButtonStyle.primary)
    async def vote_b(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._submit_vote(interaction, "b")


class RemixModal(discord.ui.Modal, title="Remix image"):
    instructions = discord.ui.TextInput(
        label="What should change?",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. add a lone figure with an umbrella in the foreground",
        required=True,
        max_length=1000,
    )

    def __init__(
        self,
        *,
        cog: "ImagineCog",
        provider_key: str,
        reference_url: str,
        base_prompt: str,
        parent_turn_id: str,
        workflow_id: str = "",
    ):
        super().__init__()
        self._cog = cog
        self._provider_key = provider_key
        self._reference_url = reference_url
        self._base_prompt = base_prompt
        self._parent_turn_id = parent_turn_id
        self._workflow_id = workflow_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        portal_user_id = await self._cog._require_portal_user(interaction, deferred=True)
        if portal_user_id is None:
            return
        prompt = f"{self._base_prompt}\n\n{self.instructions.value}".strip()
        metadata = {
            "action": "remix",
            "parent_turn_id": self._parent_turn_id,
            "strength": 0.65,
        }
        if self._workflow_id:
            metadata["workflow_id"] = self._workflow_id
        request = ImageJobInput(
            prompt=prompt,
            mode=ImageMode.EDIT,
            references=[ImageReference(source_url=self._reference_url)],
            user_id=portal_user_id,
            guild_id=str(interaction.guild_id) if interaction.guild_id else None,
            channel_id=str(interaction.channel_id) if interaction.channel_id else None,
            metadata=metadata,
        )
        await self._cog.launch_followup_job(interaction, request, self._provider_key)


class RateModal(discord.ui.Modal, title="Rate this image"):
    rating = discord.ui.TextInput(
        label="Rating (1-5)",
        placeholder="5",
        required=True,
        max_length=1,
    )

    def __init__(self, *, job_id: str):
        super().__init__()
        self._job_id = job_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = (self.rating.value or "").strip()
        if raw not in {"1", "2", "3", "4", "5"}:
            await interaction.response.send_message("Rating must be 1-5.", ephemeral=True)
            return
        await asyncio.to_thread(update_turn_rating, self._job_id, int(raw))
        logger.info("imagine_rating_recorded", job_id=self._job_id, rating=int(raw), user_id=str(interaction.user.id))
        await interaction.response.send_message(f"Thanks — recorded a {raw}/5.", ephemeral=True)


class ImagineResultView(discord.ui.View):
    """Action buttons attached to a finished /imagine result."""

    def __init__(
        self,
        *,
        cog: "ImagineCog",
        job_id: str,
        provider_key: str,
        prompt: str,
        output_url: str,
        workflow_id: str = "",
        supports_remix: bool = True,
    ):
        super().__init__(timeout=None)
        self._cog = cog
        self._job_id = job_id
        self._provider_key = provider_key
        self._prompt = prompt
        self._output_url = output_url
        self._workflow_id = workflow_id
        self._supports_remix = supports_remix
        if not supports_remix:
            for item in list(self.children):
                if getattr(item, "label", None) == "Remix":
                    self.remove_item(item)

    def _custom_id(self, action: str) -> str:
        return f"imagine|{self._job_id}|{self._workflow_id}|{action}"

    @discord.ui.button(label="Remix", style=discord.ButtonStyle.primary, custom_id="imagine:action:remix")
    async def remix(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        button.custom_id = self._custom_id("remix")
        await interaction.response.send_modal(
            RemixModal(
                cog=self._cog,
                provider_key=self._provider_key,
                reference_url=self._output_url,
                base_prompt=self._prompt,
                parent_turn_id=self._job_id,
                workflow_id=self._workflow_id,
            )
        )

    @discord.ui.button(label="Rerun", style=discord.ButtonStyle.secondary, custom_id="imagine:action:rerun")
    async def rerun(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        portal_user_id = await self._cog._require_portal_user(interaction, deferred=True)
        if portal_user_id is None:
            return
        request = ImageJobInput(
            prompt=self._prompt,
            mode=ImageMode.GENERATE,
            user_id=portal_user_id,
            guild_id=str(interaction.guild_id) if interaction.guild_id else None,
            channel_id=str(interaction.channel_id) if interaction.channel_id else None,
            metadata={"action": "rerun", "workflow_id": self._workflow_id},
        )
        await self._cog.launch_followup_job(interaction, request, self._provider_key)

    @discord.ui.button(label="Arena", style=discord.ButtonStyle.secondary, custom_id="imagine:action:arena")
    async def arena(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        portal_user_id = await self._cog._require_portal_user(interaction, deferred=True)
        if portal_user_id is None:
            return
        request = ImageJobInput(
            prompt=self._prompt,
            mode=ImageMode.ARENA,
            user_id=portal_user_id,
            guild_id=str(interaction.guild_id) if interaction.guild_id else None,
            channel_id=str(interaction.channel_id) if interaction.channel_id else None,
            metadata={"action": "arena", "workflow_id": self._workflow_id, "source_job_id": self._job_id},
        )
        await self._cog.launch_followup_job(interaction, request, self._provider_key)

    @discord.ui.button(label="Rate", style=discord.ButtonStyle.secondary, custom_id="imagine:action:rate")
    async def rate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RateModal(job_id=self._job_id))


class ImagineCog(commands.Cog):
    def __init__(self, bot: MayaBot) -> None:
        self.bot = bot
        self.image_service = get_image_service()
        self.arena = get_arena_service()
        self._tasks: set[asyncio.Task] = set()

    def _portal_base_url(self) -> str:
        return os.getenv("MAYA_PUBLIC_URL", "http://localhost:8787").rstrip("/")

    def _profile_link(self) -> str:
        return f"{self._portal_base_url()}/gateway/profile"

    def _discord_connect_link(self) -> str:
        return f"{self._portal_base_url()}/gateway/connectors/discord/start"

    def _portal_link_instructions(self) -> str:
        base = self._portal_base_url()
        return (
            "Link your Discord account before using `/imagine`:\n"
            f"1. Sign in at {base}/ with **email** (register if needed)\n"
            f"2. Open Profile ({base}/gateway/profile) → **Connect Discord**\n"
            "   (Do **not** use “Sign in with Discord” on the login page — that is for returning linked users only.)\n"
            "3. Retry `/imagine`"
        )

    def _portal_link_bypass_active(self, interaction: discord.Interaction) -> bool:
        flag = os.getenv("IMAGINE_SKIP_PORTAL_LINK", "1").strip().lower()
        if flag not in ("1", "true", "yes"):
            return False
        test_guild = os.getenv("TEST_GUILD_ID", "").strip()
        if test_guild and interaction.guild_id is not None:
            return str(interaction.guild_id) == test_guild
        return True

    async def _resolve_portal_user_id(self, interaction: discord.Interaction) -> str | None:
        from maya_image.auth.identity import resolve_discord_user_standalone

        user = await resolve_discord_user_standalone(str(interaction.user.id))
        return user.id if user else None

    async def _require_portal_user(
        self, interaction: discord.Interaction, *, deferred: bool = True
    ) -> str | None:
        portal_user_id = await self._resolve_portal_user_id(interaction)
        if portal_user_id is not None:
            return portal_user_id

        if self._portal_link_bypass_active(interaction):
            dev_user_id = os.getenv("MAYA_DEV_PORTAL_USER_ID", "").strip()
            if dev_user_id:
                logger.warning(
                    "imagine_portal_link_bypass",
                    guild_id=str(interaction.guild_id),
                    discord_user_id=str(interaction.user.id),
                    portal_user_id=dev_user_id,
                    trace_id=current_trace_id(),
                )
                return dev_user_id
            logger.error(
                "imagine_portal_bypass_missing_dev_user",
                guild_id=str(interaction.guild_id),
                hint="Set MAYA_DEV_PORTAL_USER_ID when IMAGINE_SKIP_PORTAL_LINK=1",
            )

        msg = self._portal_link_instructions()
        if deferred or interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return None

    def _track_task(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _prepare_references(
        self, attachments: list[discord.Attachment], provider_key: str
    ) -> list:
        refs = []
        for attachment in attachments:
            data = await attachment.read()
            staged = self.image_service.stage_reference(
                data=data,
                filename=attachment.filename,
                mime_type=attachment.content_type,
            )
            refs.append(await self.image_service.upload_reference(staged, provider_key=provider_key))
        return refs

    async def _send_public_message(self, interaction: discord.Interaction, **kwargs):
        channel = getattr(interaction, "channel", None)
        if channel is not None and hasattr(channel, "send"):
            try:
                return await channel.send(**kwargs)
            except Exception as exc:
                logger.warning("imagine_channel_send_failed", error=str(exc))
        return await interaction.followup.send(**kwargs)

    async def _edit_message(self, message, *, content: str | None = None) -> None:
        if message is None:
            return
        editor = getattr(message, "edit", None)
        if editor is None:
            return
        try:
            await editor(content=content)
        except Exception as exc:
            logger.warning("imagine_message_edit_failed", error=str(exc))

    async def _edit_battle_message(
        self,
        message,
        *,
        embed: discord.Embed | None = None,
        files: list[discord.File] | None = None,
        view: discord.ui.View | None | object = ...,  # noqa: ANN401
        content: str | None = None,
    ) -> None:
        if message is None:
            return
        editor = getattr(message, "edit", None)
        if editor is None:
            return
        kwargs: dict = {}
        if content is not None:
            kwargs["content"] = content
        if embed is not None:
            kwargs["embed"] = embed
        if view is not ...:
            kwargs["view"] = view
        if files is not None:
            kwargs["attachments"] = files
        try:
            await editor(**kwargs)
        except Exception as exc:
            logger.warning("imagine_battle_message_edit_failed", error=str(exc))

    async def _update_progress_throttled(
        self,
        progress_message,
        state: dict[str, float | str],
        *,
        stage: str,
        content: str,
    ) -> None:
        now = time.monotonic()
        last_edit = float(state.get("last_edit", 0.0))
        if stage == state.get("stage") and now - last_edit < _PROGRESS_EDIT_INTERVAL_SEC:
            return
        state["stage"] = stage
        state["last_edit"] = now
        emit_visibility(
            "imagine.progress",
            boundary="discord",
            stage=stage,
            message=content,
        )
        await self._edit_message(progress_message, content=content)

    def _build_comfy_progress_callback(self, progress_message, state: dict[str, float | str]):
        async def cb(stage: str, message: str) -> None:
            await self._update_progress_throttled(
                progress_message, state, stage=stage, content=message
            )

        return cb

    async def _wait_progress_ticker(self, progress_message, stop: asyncio.Event) -> None:
        updates = [
            (10.0, "ComfyUI accepted the request; loading/sampling..."),
            (20.0, "Still running... cold Krea2 can take about a minute."),
        ]
        for delay, text in updates:
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                return
            except TimeoutError:
                emit_visibility(
                    "imagine.progress.ticker",
                    boundary="discord",
                    message=text,
                )
                await self._edit_message(progress_message, content=text)

    def _progress_text(self, mode: ImageMode) -> str:
        if mode == ImageMode.ARENA:
            return "Maya is setting up the arena and rendering both contenders..."
        if mode == ImageMode.EDIT:
            return "Maya is editing the image..."
        if mode == ImageMode.REFINE:
            return "Maya is refining your creative direction…"
        return "Maya is generating the image..."

    def _file_from_output(self, output) -> tuple[discord.File | None, str]:
        local_path = output.local_path
        if local_path and Path(local_path).exists():
            filename = Path(local_path).name
            return discord.File(local_path, filename=filename), f"attachment://{filename}"
        return None, output.url

    async def _send_image_result(self, interaction: discord.Interaction, job, provider_key: str) -> None:
        output = job.output.outputs[0]
        output = await self.image_service.ensure_local_output(output)
        file, image_url = self._file_from_output(output)
        workflow_id = str((job.input.metadata or {}).get("workflow_id") or "")
        supports_remix = workflow_supports_remix(workflow_id) if workflow_id else False
        embed = discord.Embed(title=job.input.prompt[:256], color=discord.Color.purple())
        embed.add_field(name="Mode", value=job.input.mode.value, inline=True)
        embed.add_field(name="Model", value=job.output.model, inline=True)
        embed.add_field(name="Backend", value=provider_key, inline=True)
        embed.set_image(url=image_url)
        view = ImagineResultView(
            cog=self,
            job_id=job.id,
            provider_key=provider_key,
            prompt=job.input.prompt,
            output_url=output.url,
            workflow_id=workflow_id,
            supports_remix=supports_remix,
        )
        kwargs = {"embed": embed, "view": view}
        if file is not None:
            kwargs["file"] = file
        await self._send_public_message(interaction, **kwargs)

    async def launch_followup_job(
        self, interaction: discord.Interaction, request: ImageJobInput, provider_key: str
    ) -> None:
        """Run a follow-up job (rerun/remix/upscale) from a result-view button."""
        task = context_task(self._run_image_job(interaction, request, None, provider_key))
        self._track_task(task)

    async def _register_async_dispatch(self, job, provider_key: str) -> None:
        """Store Discord+turn context so the comfyui webhook can deliver cross-process.

        Only relevant when a webhook URL is configured and the job came back async
        (``SUBMITTED``); the gateway process reads this context to post the result and
        record the AGE turn when the comfyui-api completion webhook fires.
        """
        if not os.getenv("MAYA_COMFYUI_WEBHOOK_URL"):
            return
        if job.status != ImageJobStatus.SUBMITTED or not job.provider_job_id:
            return
        meta = job.input.metadata or {}
        context = {
            "turn_id": job.id,
            "provider_key": provider_key,
            "prompt": job.input.prompt,
            "channel_id": job.input.channel_id,
            "user_id": job.input.user_id,
            "progress_message_id": meta.get("discord_message_id"),
            "seed": meta.get("seed"),
            "aspect": job.input.size,
            "action": meta.get("action", job.input.mode.value),
            "parent_turn_id": meta.get("parent_turn_id"),
            "reference_urls": [ref.source_url for ref in job.input.references],
            "strength": meta.get("strength"),
            "workflow_id": meta.get("workflow_id"),
            "source": "discord",
            "trace_id": meta.get("trace_id") or current_trace_id(),
            "span_id": meta.get("span_id") or current_span_id(),
        }
        try:
            await store_dispatch_context(job.provider_job_id, context)
        except Exception as exc:
            logger.warning("imagine_dispatch_context_failed", job_id=job.id, error=str(exc))

    async def _persist_turn(self, job, provider_key: str) -> None:
        """Best-effort: record this generation as an ImageTurn node in AGE."""
        output = job.output.outputs[0]
        meta = job.input.metadata or {}
        try:
            await asyncio.to_thread(
                record_image_turn,
                turn_id=job.id,
                generation_id=job.provider_job_id or job.id,
                provider=provider_key,
                model=job.output.model,
                prompt_raw=job.input.prompt,
                prompt_expanded=job.output.revised_prompt,
                seed=meta.get("seed"),
                aspect=job.input.size,
                image_url=output.url,
                action=meta.get("action", job.input.mode.value),
                discord_message_id=meta.get("discord_message_id"),
                parent_turn_id=meta.get("parent_turn_id"),
                reference_urls=[ref.source_url for ref in job.input.references],
                strength=meta.get("strength"),
                workflow_id=meta.get("workflow_id"),
                source="discord",
                user_id=job.input.user_id,
            )
        except Exception as exc:
            logger.warning("imagine_turn_persist_failed", error=str(exc), job_id=job.id)
            return
        if job.input.user_id:
            from maya_image.portal.activity import emit_event_standalone

            output = job.output.outputs[0] if job.output and job.output.outputs else None
            await emit_event_standalone(
                user_id=job.input.user_id,
                kind="image.job_completed",
                title="Image ready",
                body=(job.input.prompt or "")[:200],
                link=output.url if output else None,
                source="discord",
                metadata={"job_id": job.id, "provider": provider_key},
            )

    def _build_arena_embed(self, state: _ArenaBattleState) -> discord.Embed:
        label_a = state.contender_labels.get("a", "unknown")
        label_b = state.contender_labels.get("b", "unknown")
        embed = discord.Embed(
            title="Imagine A/B comparison",
            description=state.request.prompt[:500],
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Battle ID", value=state.battle_id, inline=False)
        embed.add_field(
            name="Vote",
            value=(
                "Compare **A** (left) and **B** (right). "
                "Use the A / Tie / B buttons below to pick the overall winner."
            ),
            inline=False,
        )
        embed.add_field(
            name="Models (spoiler — vote first)",
            value=f"||A: {label_a} · B: {label_b}||",
            inline=False,
        )
        embed.set_image(url=f"attachment://{_ARENA_COMPOSITE_FILENAME}")
        return embed

    def _arena_slot_placeholder(self, state: _ArenaBattleState, slot: str) -> str:
        job = state.slots.get(slot)
        if job is None:
            return "Generating…"
        if job.status == ImageJobStatus.FAILED:
            return "Generation failed"
        if job.status == ImageJobStatus.COMPLETED:
            if state.slot_paths.get(slot):
                return "Ready"
            return "Generating…"
        return "Generating…"

    def _arena_composite_file(self, state: _ArenaBattleState) -> discord.File:
        left_raw = state.slot_paths.get("a")
        right_raw = state.slot_paths.get("b")
        left_path = Path(left_raw) if left_raw else None
        right_path = Path(right_raw) if right_raw else None
        composite_path = build_side_by_side(
            left_path if left_path and left_path.is_file() else None,
            right_path if right_path and right_path.is_file() else None,
            left_placeholder=self._arena_slot_placeholder(state, "a"),
            right_placeholder=self._arena_slot_placeholder(state, "b"),
            output_dir=Path(tempfile.gettempdir()) / "maya-arena",
        )
        return discord.File(composite_path, filename=_ARENA_COMPOSITE_FILENAME)

    def _arena_vote_enabled(self, state: _ArenaBattleState) -> bool:
        job_a = state.slots.get("a")
        job_b = state.slots.get("b")
        if not job_a or not job_b:
            return False
        if job_a.status == ImageJobStatus.FAILED and job_b.status == ImageJobStatus.FAILED:
            return False

        def _completed(job: ImageJob | None) -> bool:
            return bool(
                job
                and job.status == ImageJobStatus.COMPLETED
                and job.output
                and job.output.outputs
            )

        return _completed(job_a) or _completed(job_b)

    async def _apply_job_to_state(self, state: _ArenaBattleState, slot: str, job: ImageJob) -> None:
        state.slots[slot] = job
        if job.output and job.output.outputs:
            output = await self.image_service.ensure_local_output(job.output.outputs[0], subdir="arena")
            state.slot_paths[slot] = output.local_path

    async def _refresh_arena_battle_message(
        self,
        message,
        state: _ArenaBattleState,
        *,
        vote_enabled: bool | None = None,
    ) -> None:
        if vote_enabled is None:
            vote_enabled = self._arena_vote_enabled(state)

        job_a = state.slots.get("a")
        job_b = state.slots.get("b")
        if (
            job_a
            and job_b
            and job_a.status == ImageJobStatus.FAILED
            and job_b.status == ImageJobStatus.FAILED
        ):
            labels = state.contender_labels
            embed = discord.Embed(
                title="Arena battle failed",
                description="Both providers failed to generate an image.",
                color=discord.Color.red(),
            )
            embed.add_field(
                name="A",
                value=(job_a.error or "unknown error")[:300],
                inline=False,
            )
            embed.add_field(
                name="B",
                value=(job_b.error or "unknown error")[:300],
                inline=False,
            )
            embed.add_field(name="Battle ID", value=state.battle_id, inline=False)
            await self._edit_battle_message(message, embed=embed, files=[], view=discord.ui.View())
            return

        embed = self._build_arena_embed(state)
        composite = self._arena_composite_file(state)
        view = ArenaVoteView(battle_id=state.battle_id, enabled=vote_enabled)
        await self._edit_battle_message(message, embed=embed, files=[composite], view=view)

    async def _post_arena_battle_message(
        self,
        interaction: discord.Interaction,
        state: _ArenaBattleState,
        *,
        vote_enabled: bool,
    ) -> discord.Message:
        embed = self._build_arena_embed(state)
        composite = self._arena_composite_file(state)
        view = ArenaVoteView(battle_id=state.battle_id, enabled=vote_enabled)
        return await self._send_public_message(
            interaction,
            embed=embed,
            files=[composite],
            view=view,
        )

    async def _handle_arena_policy_forfeits(self, state: _ArenaBattleState) -> None:
        candidate_ids = state.result.get("candidate_ids") or {}
        for slot in ("a", "b"):
            job = state.slots.get(slot)
            cid = candidate_ids.get(slot)
            if not job or not cid:
                continue
            if job.status == ImageJobStatus.FAILED and "content_policy_violation" in (job.error or ""):
                try:
                    await asyncio.to_thread(
                        self.arena.forfeit_battle,
                        state.battle_id,
                        cid,
                        "content_policy",
                    )
                except Exception:
                    pass

        job_a = state.slots.get("a")
        job_b = state.slots.get("b")
        if (
            job_a
            and job_b
            and job_a.status == ImageJobStatus.FAILED
            and job_b.status == ImageJobStatus.FAILED
        ):
            for slot in ("a", "b"):
                cid = candidate_ids.get(slot)
                if cid:
                    try:
                        await asyncio.to_thread(
                            self.arena.forfeit_battle,
                            state.battle_id,
                            cid,
                            "provider_failed",
                        )
                    except Exception:
                        pass

    async def _run_progressive_arena(
        self,
        interaction: discord.Interaction,
        request: ImageJobInput,
        result: dict,
    ) -> tuple[_ArenaBattleState, discord.Message]:
        state = _ArenaBattleState(
            battle_id=result["battle_id"],
            request=request,
            result=result,
            contender_labels=dict(result.get("contender_labels") or {}),
        )
        for slot in ("a", "b"):
            job_id = result["job_ids"].get(slot)
            if not job_id:
                continue
            job = self.image_service.get_memory_job(job_id)
            if job and job.status in {ImageJobStatus.COMPLETED, ImageJobStatus.FAILED}:
                await self._apply_job_to_state(state, slot, job)
        battle_message = await self._post_arena_battle_message(
            interaction, state, vote_enabled=False
        )
        refresh_lock = asyncio.Lock()

        async def refresh(*, vote_enabled: bool | None = None) -> None:
            async with refresh_lock:
                await self._refresh_arena_battle_message(
                    battle_message, state, vote_enabled=vote_enabled
                )

        if state.slots:
            await refresh(vote_enabled=False)

        async def watch_slot(slot: str) -> ImageJob:
            job = await self.image_service.wait_for_job(
                result["job_ids"][slot],
                max_polls=_ARENA_MAX_POLLS,
                poll_interval=5.0,
                timeout_sec=float(_GENERATION_TIMEOUT_SEC),
            )
            await self._apply_job_to_state(state, slot, job)
            await refresh(vote_enabled=False)
            return job

        await asyncio.gather(watch_slot("a"), watch_slot("b"))

        finalized = await self.image_service.finalize_arena_jobs(
            result["battle_id"],
            result["job_ids"],
            result["candidate_ids"],
            max_polls=1,
            poll_interval=0,
            timeout_sec=1.0,
        )
        for slot, job in finalized.items():
            await self._apply_job_to_state(state, slot, job)

        vote_enabled = self._arena_vote_enabled(state)
        await refresh(vote_enabled=vote_enabled)
        await self._handle_arena_policy_forfeits(state)

        if vote_enabled:
            session_task = context_task(
                self._persist_arena_session(
                    battle_id=state.battle_id,
                    started_by=str(interaction.user.id),
                    channel_id=str(interaction.channel_id),
                    guild_id=str(interaction.guild_id) if interaction.guild_id else None,
                    message_id=str(battle_message.id),
                )
            )
            self._track_task(session_task)

        return state, battle_message

    async def _refresh_arena_from_salvage(
        self,
        battle_message,
        request: ImageJobInput,
        salvaged: dict,
    ) -> None:
        state = _ArenaBattleState(
            battle_id=salvaged["battle_id"],
            request=request,
            result=salvaged,
            contender_labels=dict(salvaged.get("contender_labels") or {}),
        )
        for slot in ("a", "b"):
            job = salvaged.get(slot)
            if job:
                await self._apply_job_to_state(state, slot, job)
        vote_enabled = self._arena_vote_enabled(state)
        await self._refresh_arena_battle_message(battle_message, state, vote_enabled=vote_enabled)
        await self._handle_arena_policy_forfeits(state)

    async def _send_arena_result_fallback(
        self,
        interaction: discord.Interaction,
        request: ImageJobInput,
        result: dict,
        *,
        contender_labels: dict[str, str] | None = None,
    ) -> None:
        """Post a single battle message when progressive UI was not started (salvage fallback)."""
        state = _ArenaBattleState(
            battle_id=result["battle_id"],
            request=request,
            result=result,
            contender_labels=dict(contender_labels or result.get("contender_labels") or {}),
        )
        for slot in ("a", "b"):
            job = result.get(slot)
            if job:
                await self._apply_job_to_state(state, slot, job)
        vote_enabled = self._arena_vote_enabled(state)
        if not vote_enabled and not any(state.slots.get(s) for s in ("a", "b")):
            raise TimeoutError("Arena generation timed out before both outputs completed.")
        battle_message = await self._post_arena_battle_message(
            interaction, state, vote_enabled=vote_enabled
        )
        if vote_enabled:
            session_task = context_task(
                self._persist_arena_session(
                    battle_id=state.battle_id,
                    started_by=str(interaction.user.id),
                    channel_id=str(interaction.channel_id),
                    guild_id=str(interaction.guild_id) if interaction.guild_id else None,
                    message_id=str(battle_message.id),
                )
            )
            self._track_task(session_task)
        await self._handle_arena_policy_forfeits(state)

    async def _persist_arena_session(
        self,
        *,
        battle_id: str,
        started_by: str,
        channel_id: str | None,
        guild_id: str | None,
        message_id: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self.arena.create_session,
                battle_id=battle_id,
                started_by=started_by,
                channel_id=channel_id,
                guild_id=guild_id,
                message_id=message_id,
            )
        except Exception as exc:
            logger.warning("arena_session_create_failed", error=str(exc), battle_id=battle_id)

    async def _run_image_job(
        self,
        interaction: discord.Interaction,
        request: ImageJobInput,
        progress_message,
        provider_key: str = _DEFAULT_PROVIDER_KEY,
    ) -> None:
        with _tracer.start_as_current_span("discord.imagine.run") as span:
            # The platform decides: default a plain generate to a concurrent blind A/B
            # arena turn (shared with the web feed via lib.image.mode_resolver). Explicit
            # arena/edit choices and the MAYA_ARENA_DEFAULT kill-switch are honored.
            request.mode = resolve_generation_mode(request)
            span.set_attribute("image.mode", request.mode.value)
            span.set_attribute("image.provider_key", provider_key)
            for key in (
                "discord_interaction_id",
                "discord_message_id",
            ):
                value = request.metadata.get(key)
                if value:
                    span.set_attribute(key.replace("_", "."), value)
            if request.user_id:
                span.set_attribute("discord.user_id", request.user_id)
            arena_contender_labels: dict[str, str] | None = None
            arena_battle_message = None
            try:
                sync_stack_window(span)
                emit_visibility(
                    "imagine.job.start",
                    span=span,
                    boundary="discord",
                    mode=request.mode.value,
                    provider_key=provider_key,
                    deadline_sec=_JOB_HARD_DEADLINE_SEC,
                )
                with push_frame("discord.imagine.run"):
                    async with asyncio.timeout(float(_JOB_HARD_DEADLINE_SEC)):
                        if request.mode == ImageMode.ARENA:
                            if request.metadata.get("workflow_id"):
                                result = await self.image_service.submit_workflow_arena(request)
                            else:
                                result = await self.image_service.submit_arena(request)
                            arena_contender_labels = result.get("contender_labels")
                            span.set_attribute("image.battle_id", result.get("battle_id", ""))
                            arena_state, arena_battle_message = await self._run_progressive_arena(
                                interaction, request, result
                            )
                            job_a = arena_state.slots.get("a")
                            job_b = arena_state.slots.get("b")
                            a_ok = bool(
                                job_a
                                and job_a.status == ImageJobStatus.COMPLETED
                                and job_a.output
                                and job_a.output.outputs
                            )
                            b_ok = bool(
                                job_b
                                and job_b.status == ImageJobStatus.COMPLETED
                                and job_b.output
                                and job_b.output.outputs
                            )
                            if a_ok and b_ok:
                                await self._edit_message(
                                    progress_message, content="Image request completed."
                                )
                            elif (
                                job_a
                                and job_b
                                and job_a.status == ImageJobStatus.FAILED
                                and job_b.status == ImageJobStatus.FAILED
                            ):
                                await self._edit_message(
                                    progress_message,
                                    content="Arena generation failed for both contenders.",
                                )
                            elif (job_a and job_a.status == ImageJobStatus.FAILED) or (
                                job_b and job_b.status == ImageJobStatus.FAILED
                            ):
                                await self._edit_message(
                                    progress_message, content="Image request completed."
                                )
                            else:
                                await self._edit_message(
                                    progress_message,
                                    content="Arena generation timed out before both outputs completed.",
                                )
                        else:
                            progress_state: dict[str, float | str] = {}
                            progress_cb = None
                            if provider_key == "comfyui:graph" and progress_message is not None:
                                await self._edit_message(
                                    progress_message, content="Checking GPU and workflow..."
                                )
                                progress_cb = self._build_comfy_progress_callback(
                                    progress_message, progress_state
                                )
                            with push_frame("image.submit"):
                                job = await self.image_service.submit(
                                    provider_key, request, progress_cb=progress_cb
                                )
                            await self._register_async_dispatch(job, provider_key)
                            stop_ticker = asyncio.Event()
                            ticker_task = None
                            if progress_message is not None and job.status == ImageJobStatus.PROCESSING:
                                ticker_task = context_task(
                                    self._wait_progress_ticker(progress_message, stop_ticker)
                                )
                            try:
                                with push_frame("image.wait_for_job"):
                                    job = await self.image_service.wait_for_job(
                                        job.id,
                                        max_polls=_ARENA_MAX_POLLS,
                                        poll_interval=5.0,
                                        timeout_sec=float(_GENERATION_TIMEOUT_SEC),
                                    )
                            finally:
                                stop_ticker.set()
                                if ticker_task is not None:
                                    ticker_task.cancel()
                            if job.status == ImageJobStatus.FAILED:
                                raise RuntimeError(job.error or "provider_failed")
                            if not job.output or not job.output.outputs:
                                raise TimeoutError(
                                    f"Image generation timed out after {_GENERATION_TIMEOUT_SEC}s."
                                )
                            # Idempotency guard: the comfyui webhook may have already delivered
                            # this job (and recorded its turn) from the gateway process.
                            if job.provider_job_id and not await mark_dispatched(job.provider_job_id):
                                logger.info("imagine_delivery_claimed_by_webhook", job_id=job.id)
                            else:
                                await self._send_image_result(interaction, job, provider_key)
                                self._track_task(
                                    context_task(self._persist_turn(job, provider_key))
                                )
                            emit_visibility(
                                "imagine.job.done",
                                span=span,
                                boundary="discord",
                                job_id=job.id,
                                status=job.status.value,
                            )
                            await self._edit_message(
                                progress_message, content="Image request completed."
                            )
            except TimeoutError as exc:
                span.record_exception(exc)
                trace_id = current_trace_id()
                emit_visibility(
                    "imagine.job.hard_timeout",
                    span=span,
                    boundary="discord",
                    deadline_sec=_JOB_HARD_DEADLINE_SEC,
                    error=str(exc),
                    trace_id=trace_id,
                )
                logger.error(
                    "imagine_job_hard_timeout",
                    error=str(exc) or "hard_deadline",
                    deadline_sec=_JOB_HARD_DEADLINE_SEC,
                    trace_id=trace_id,
                )
                salvaged = False
                if request.mode == ImageMode.ARENA:
                    salvaged_result = await self.image_service.salvage_inflight_arena(
                        request,
                        contender_labels=arena_contender_labels,
                    )
                    if salvaged_result:
                        if arena_battle_message is not None:
                            await self._refresh_arena_from_salvage(
                                arena_battle_message, request, salvaged_result
                            )
                        else:
                            await self._send_arena_result_fallback(
                                interaction,
                                request,
                                salvaged_result,
                                contender_labels=salvaged_result.get("contender_labels"),
                            )
                        await self._edit_message(
                            progress_message,
                            content="Image request completed (partial — one slot timed out).",
                        )
                        salvaged = True
                if not salvaged:
                    message = (
                        str(exc)
                        if str(exc)
                        else f"Generation timed out after {_GENERATION_TIMEOUT_SEC}s."
                    )
                    if os.getenv("ENVIRONMENT", "development") == "development" and trace_id:
                        message = f"{message}\n(trace: `{trace_id}`)"
                    await self._edit_message(progress_message, content=message)
            except Exception as exc:
                span.record_exception(exc)
                trace_id = current_trace_id()
                emit_visibility(
                    "imagine.job.failed",
                    span=span,
                    boundary="discord",
                    error=str(exc),
                    trace_id=trace_id,
                )
                logger.error("imagine_background_failed", error=str(exc), trace_id=trace_id)
                message = f"Generation failed: {exc}" if str(exc) else "Generation failed."
                if os.getenv("ENVIRONMENT", "development") == "development" and trace_id:
                    message = f"{message}\n(trace: `{trace_id}`)"
                await self._edit_message(progress_message, content=message)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == getattr(self.bot.user, "id", None):
            return
        emoji_value = payload.emoji.name or str(payload.emoji)
        try:
            await asyncio.to_thread(
                self.arena.record_reaction_by_message,
                message_id=str(payload.message_id),
                user_id=str(payload.user_id),
                username=str(payload.user_id),
                reaction=emoji_value,
            )
        except Exception:
            return

    @app_commands.command(name="imagine", description="Generate, edit, or arena-test images")
    @app_commands.describe(
        prompt="Prompt for the image workflow",
        mode="Generate, edit, or arena",
        model="Image model / provider (default: Ideogram 4.0)",
        size="Image dimensions",
        quality="Quality setting",
        reference_1="First reference image",
        reference_2="Second reference image",
        reference_3="Third reference image",
        reference_4="Fourth reference image",
        reference_5="Fifth reference image",
        reference_6="Sixth reference image",
    )
    @app_commands.choices(mode=_MODE_CHOICES, model=_MODEL_CHOICES)
    async def imagine(
        self,
        interaction: discord.Interaction,
        prompt: str,
        mode: app_commands.Choice[str],
        model: Optional[app_commands.Choice[str]] = None,
        size: str = "1024x1024",
        quality: str = "high",
        reference_1: Optional[discord.Attachment] = None,
        reference_2: Optional[discord.Attachment] = None,
        reference_3: Optional[discord.Attachment] = None,
        reference_4: Optional[discord.Attachment] = None,
        reference_5: Optional[discord.Attachment] = None,
        reference_6: Optional[discord.Attachment] = None,
    ) -> None:
        await interaction.response.defer()
        portal_user_id = await self._require_portal_user(interaction, deferred=True)
        if portal_user_id is None:
            return
        interaction_id = str(getattr(interaction, "id", "") or "")
        discord_user_id = str(interaction.user.id)
        channel_id = str(interaction.channel_id) if interaction.channel_id else None
        guild_id = str(interaction.guild_id) if interaction.guild_id else None
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            discord_interaction_id=interaction_id,
            discord_user_id=discord_user_id,
            portal_user_id=portal_user_id,
            discord_channel_id=channel_id,
            discord_guild_id=guild_id,
            image_mode=mode.value,
        )
        req_ctx = RequestContext.new(
            "discord",
            actor=ActorContext(
                id=portal_user_id,
                kind="user",
                display_name=getattr(interaction.user, "display_name", None),
            ),
        )
        with set_request_context(req_ctx):
            with push_frame("discord.imagine"):
                with _tracer.start_as_current_span("discord.imagine") as span:
                    sync_stack_window(span)
                    span.set_attribute("discord.interaction_id", interaction_id)
                    span.set_attribute("discord.user_id", discord_user_id)
                    span.set_attribute("portal.user_id", portal_user_id)
                    if channel_id:
                        span.set_attribute("discord.channel_id", channel_id)
                    if guild_id:
                        span.set_attribute("discord.guild_id", guild_id)
                    span.set_attribute("image.mode", mode.value)
                    span.set_attribute("image.prompt_length", len(prompt))
                    model_value = model.value if model is not None else None
                    workflow = resolve_workflow(model_value, mode=mode.value)
                    provider_key = workflow.provider_key or _DEFAULT_PROVIDER_KEY
                    span.set_attribute("image.provider_key", provider_key)
                    span.set_attribute("image.workflow_id", workflow.id)
                    emit_visibility(
                        "imagine.command",
                        span=span,
                        boundary="discord",
                        mode=mode.value,
                        provider_key=provider_key,
                        workflow_id=workflow.id,
                    )
                    await self._imagine_impl(
                        interaction,
                        prompt,
                        mode,
                        size,
                        quality,
                        [reference_1, reference_2, reference_3, reference_4, reference_5, reference_6],
                        interaction_id=interaction_id,
                        provider_key=provider_key,
                        workflow=workflow,
                        portal_user_id=portal_user_id,
                    )

    async def _imagine_impl(
        self,
        interaction: discord.Interaction,
        prompt: str,
        mode: app_commands.Choice[str],
        size: str,
        quality: str,
        attachment_slots: list[Optional[discord.Attachment]],
        *,
        interaction_id: str,
        provider_key: str = _DEFAULT_PROVIDER_KEY,
        workflow: ImageWorkflow | None = None,
        portal_user_id: str | None = None,
    ) -> None:
        try:
            if portal_user_id is None:
                portal_user_id = await self._require_portal_user(interaction, deferred=True)
                if portal_user_id is None:
                    return
            image_mode = ImageMode(mode.value)
            if image_mode == ImageMode.REFINE:
                await self._run_refine_agent(
                    interaction,
                    prompt=prompt,
                    portal_user_id=portal_user_id,
                    size=size,
                )
                return
            attachments = [att for att in attachment_slots if att is not None]
            wf = workflow or resolve_workflow(None, mode=mode.value)

            if image_mode in _REFERENCE_REQUIRED and not attachments:
                await interaction.followup.send(
                    f"`{image_mode.value}` mode requires at least one reference image.",
                    ephemeral=True,
                )
                return

            try:
                references = await self._prepare_references(attachments, provider_key)
            except Exception as exc:
                logger.error("imagine_reference_prepare_failed", error=str(exc))
                await interaction.followup.send(
                    f"Failed to upload reference image: {exc}",
                    ephemeral=True,
                )
                return

            request = ImageJobInput(
                prompt=prompt,
                mode=image_mode,
                references=references,
                size=size,
                quality=quality,
                user_id=portal_user_id,
                guild_id=str(interaction.guild_id) if interaction.guild_id else None,
                channel_id=str(interaction.channel_id),
                metadata={
                    "discord_interaction_id": interaction_id,
                    "discord_user_id": str(interaction.user.id),
                    "provider_key": provider_key,
                    "workflow_id": wf.id,
                },
            )

            from maya_image.portal.activity import emit_event_standalone

            await emit_event_standalone(
                user_id=portal_user_id,
                kind="image.job_started",
                title=f"/imagine {image_mode.value}",
                body=prompt[:200],
                source="discord",
                metadata={"mode": image_mode.value, "provider_key": provider_key},
            )

            try:
                progress_message = await interaction.edit_original_response(
                    content=self._progress_text(image_mode)
                )
            except Exception as exc:
                logger.warning("imagine_progress_post_failed", error=str(exc))
                progress_message = None
            if progress_message is not None:
                progress_message_id = str(getattr(progress_message, "id", "") or "")
                if progress_message_id:
                    request.metadata["discord_message_id"] = progress_message_id
                    structlog.contextvars.bind_contextvars(
                        discord_message_id=progress_message_id
                    )
                    span = trace.get_current_span()
                    if span is not None:
                        span.set_attribute("discord.message_id", progress_message_id)

            task = context_task(
                self._run_image_job(interaction, request, progress_message, provider_key)
            )
            self._track_task(task)
        except Exception as exc:
            logger.exception("imagine_unhandled_error", error=str(exc))
            await interaction.followup.send(
                f"Image request failed: {exc}",
                ephemeral=True,
            )

    async def _run_refine_agent(
        self,
        interaction: discord.Interaction,
        *,
        prompt: str,
        portal_user_id: str,
        size: str,
    ) -> None:
        await interaction.followup.send(
            "Refine mode is not available in the public self-hosted build.",
            ephemeral=True,
        )


async def setup(bot: MayaBot) -> None:
    cog = ImagineCog(bot)
    await bot.add_cog(cog)
    bot.add_view(
        ImagineResultView(
            cog=cog,
            job_id="persistent",
            provider_key=_DEFAULT_PROVIDER_KEY,
            prompt="",
            output_url="",
            workflow_id="",
        )
    )
