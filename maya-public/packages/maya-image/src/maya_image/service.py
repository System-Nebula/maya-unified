"""Image service for fal-backed generation, editing, and arena orchestration."""

from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from opentelemetry import trace
from sqlalchemy.exc import SQLAlchemyError

from maya_image.arena.service import ArenaService, get_arena_service
from maya_image.arena_pair import arena_pair_from_env
from maya_db.models.arena import ArenaBattle, ArenaCandidate
from maya_db.sync_connection import get_sync_connection
from maya_db.models.image_job import ImageJobTable
from maya_image.comfy_bind import is_arena_request, normalize_arena_resolution
from maya_image.storage import ImageStorage
from maya_image.providers import ComfyUIGraphProvider, IdeogramProvider
from maya_image.workflows import (
    apply_workflow_to_request,
    get_workflow,
    list_arena_runnable_workflows,
    resolve_provider_key,
    workflow_is_arena_runnable,
)
from maya_image.types.image_job import ImageJob, ImageJobInput, ImageJobOutput, ImageJobStatus, ImageOutput, ImageReference, ImageMode

ImageProgressCallback = Callable[[str, str], Awaitable[None]]

try:
    from observability import current_trace_id as _current_trace_id
except ImportError:
    def _current_trace_id() -> Optional[str]:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None
        return format(ctx.trace_id, "032x")


logger = structlog.get_logger()
_tracer = trace.get_tracer("image.service")
_DB_OP_TIMEOUT_SEC = float(os.getenv("MAYA_IMAGE_DB_TIMEOUT_SEC", "8"))


def current_trace_id() -> Optional[str]:
    """Return the active OpenTelemetry trace id as a hex string, if any."""
    return _current_trace_id()


def arena_max_contenders(*, for_studio: bool = False) -> int:
    """Max arena slots; Discord always clamps to 2, studio may use MAYA_ARENA_MAX_CONTENDERS."""
    if not for_studio:
        return 2
    raw = os.getenv("MAYA_ARENA_MAX_CONTENDERS", "2")
    try:
        return max(2, int(raw))
    except ValueError:
        return 2


def _arena_slot_names(count: int) -> list[str]:
    if count < 2:
        raise ValueError("Arena requires at least 2 contenders")
    return ["a", "b"] + [f"c{i}" for i in range(3, count + 1)]


class ImageJobService:
    def __init__(self):
        self._db = get_sync_connection()
        self._providers = {
            "comfyui:graph": ComfyUIGraphProvider(),
        }
        if os.getenv("MAYA_ENABLE_HOSTED_PROVIDERS", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            self._register_hosted_providers()
        if os.getenv("MAYA_FAKE_COMFY", "").strip().lower() in {"1", "true", "yes", "on"}:
            from maya_image.providers.fake_comfy import FakeComfyGraphProvider

            self._providers["comfyui:graph"] = FakeComfyGraphProvider()
            logger.info("image_service_using_fake_comfy_provider")
        self._storage = ImageStorage()
        self._arena: ArenaService = get_arena_service()
        self._memory_jobs: dict[str, ImageJob] = {}

    def _register_hosted_providers(self) -> None:
        """Register optional fal/hosted Ideogram providers when keys are configured."""
        try:
            from maya_image.providers import FalGPTImage2Provider, FalNanoBanana2Provider
            from maya_image.providers.hidream import FalHiDreamO1ImageProvider
            from maya_image.providers.hunyuan import FalHunyuanImage3Provider
            from maya_image.providers.kling import FalKlingImage3OmniProvider
            from maya_image.providers.luma import FalLumaUni1MaxProvider
            from maya_image.providers.qwen import FalQwenImageEditPlusProvider
            from maya_image.providers.wan import FalWan27Provider

            self._providers.update(
                {
                    "fal:gpt-image-2": FalGPTImage2Provider(),
                    "fal:nano-banana-2": FalNanoBanana2Provider(),
                    "fal:hunyuan-image-3": FalHunyuanImage3Provider(),
                    "fal:luma-uni-1-max": FalLumaUni1MaxProvider(),
                    "fal:kling-image-3-omni": FalKlingImage3OmniProvider(),
                    "fal:hidream-o1-image": FalHiDreamO1ImageProvider(),
                    "fal:wan-2.7": FalWan27Provider(),
                    "fal:qwen-image-edit-plus": FalQwenImageEditPlusProvider(),
                    "ideogram:4": IdeogramProvider(),
                }
            )
        except Exception as exc:
            logger.warning("hosted_image_providers_unavailable", error=str(exc))

    def get_memory_job(self, job_id: str) -> ImageJob | None:
        return self._memory_jobs.get(job_id)

    def _session(self):
        return self._db.get_session()

    def _provider(self, provider_key: str):
        provider = self._providers.get(provider_key)
        if provider is None:
            raise ValueError(f"Unsupported image provider: {provider_key}")
        return provider

    async def _to_thread(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    async def _db_op(self, label: str, func, *args, **kwargs):
        started = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._to_thread(func, *args, **kwargs),
                timeout=_DB_OP_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "image_db_op_timeout",
                label=label,
                timeout_sec=_DB_OP_TIMEOUT_SEC,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            return None
        except SQLAlchemyError as exc:
            logger.warning(
                "image_db_op_failed",
                label=label,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None
        except Exception as exc:
            logger.warning(
                "image_db_op_failed",
                label=label,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None

    async def _required_db_op(self, label: str, func, *args, **kwargs):
        result = await self._db_op(label, func, *args, **kwargs)
        if result is None:
            raise RuntimeError(f"Database operation failed or timed out: {label}")
        return result

    def _memory_arena_candidate_sync(
        self,
        *,
        modality: str,
        provider: str,
        model_key: str,
        display_name: str,
    ) -> ArenaCandidate:
        candidate = ArenaCandidate(
            id=str(uuid.uuid4()),
            name=display_name,
            modality=modality,
            provider=provider,
            model_key=model_key,
            rating=1200,
            rating_deviation=350,
            wins=0,
            losses=0,
            draws=0,
            total_battles=0,
            win_rate=0.0,
            is_active=True,
        )
        return self._arena._store_candidate(candidate)

    def _memory_arena_battle_sync(
        self,
        candidate_a_id: str,
        candidate_b_id: str,
        prompt: str,
        prompt_source: str | None,
        *,
        modality: str,
        input_payload: dict | None,
    ) -> ArenaBattle:
        candidate_a = self._arena.get_candidate(candidate_a_id)
        candidate_b = self._arena.get_candidate(candidate_b_id)
        if not candidate_a or not candidate_b:
            raise ValueError("One or both arena candidates not found in memory cache")
        battle = ArenaBattle(
            id=str(uuid.uuid4()),
            modality=modality or candidate_a.modality,
            candidate_a_id=candidate_a_id,
            candidate_b_id=candidate_b_id,
            prompt=prompt,
            prompt_source=prompt_source,
            input_payload=input_payload or {},
            status="voting",
            votes_a=0,
            votes_b=0,
            votes_tie=0,
            total_votes=0,
            started_at=datetime.utcnow(),
        )
        return self._arena._store_battle(battle)

    async def _ensure_arena_candidate(
        self,
        *,
        modality: str,
        provider: str,
        model_key: str,
        display_name: str,
    ) -> ArenaCandidate:
        candidate = await self._db_op(
            "arena.ensure_candidate",
            self._arena.ensure_candidate,
            modality=modality,
            provider=provider,
            model_key=model_key,
            display_name=display_name,
        )
        if candidate is not None:
            return candidate
        logger.warning(
            "arena_ensure_candidate_fallback",
            modality=modality,
            provider=provider,
            model_key=model_key,
        )
        return await self._to_thread(
            self._memory_arena_candidate_sync,
            modality=modality,
            provider=provider,
            model_key=model_key,
            display_name=display_name,
        )

    async def _create_arena_battle(
        self,
        candidate_a_id: str,
        candidate_b_id: str,
        prompt: str,
        prompt_source: str | None,
        *,
        modality: str,
        input_payload: dict | None,
    ) -> ArenaBattle:
        battle = await self._db_op(
            "arena.create_battle",
            self._arena.create_battle,
            candidate_a_id,
            candidate_b_id,
            prompt,
            prompt_source,
            modality=modality,
            input_payload=input_payload,
        )
        if battle is not None:
            return battle
        logger.warning(
            "arena_create_battle_fallback",
            candidate_a_id=candidate_a_id,
            candidate_b_id=candidate_b_id,
        )
        return await self._to_thread(
            self._memory_arena_battle_sync,
            candidate_a_id,
            candidate_b_id,
            prompt,
            prompt_source,
            modality=modality,
            input_payload=input_payload,
        )

    def _build_job_record(self, job: ImageJob) -> ImageJobTable:
        return ImageJobTable(
            id=job.id,
            user_id=job.input.user_id,
            provider_key=job.provider_key,
            provider_job_id=job.provider_job_id,
            status=job.status.value,
            mode=job.input.mode.value,
            prompt=job.input.prompt,
            size=job.input.size,
            quality=job.input.quality,
            mask_url=job.input.mask_url,
            references=[ref.model_dump() for ref in job.input.references],
            extra_data=job.input.metadata,
            started_at=job.started_at,
        )

    def _load_job_record_sync(self, job_id: str) -> dict | None:
        session = self._session()
        row = session.query(ImageJobTable).filter(ImageJobTable.id == job_id).first()
        if row is None:
            return None
        return {
            "id": row.id,
            "provider_key": row.provider_key,
            "provider_job_id": row.provider_job_id,
            "status": row.status,
            "prompt": row.prompt,
            "mode": row.mode,
            "size": row.size,
            "quality": row.quality,
            "mask_url": row.mask_url,
            "references": list(row.references or []),
            "extra_data": dict(row.extra_data or {}),
            "output": row.output,
            "error": row.error,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }

    def _persist_job_sync(self, job: ImageJob) -> None:
        session = self._session()
        session.add(self._build_job_record(job))
        session.commit()

    def _persist_job_state_sync(
        self,
        *,
        job_id: str,
        status: ImageJobStatus,
        output: ImageJobOutput | None = None,
        error: str | None = None,
    ) -> None:
        session = self._session()
        row = session.query(ImageJobTable).filter(ImageJobTable.id == job_id).first()
        if row is None:
            return
        row.status = status.value
        if output is not None:
            row.output = output.model_dump()
        if error is not None:
            row.error = error
        if status in {ImageJobStatus.COMPLETED, ImageJobStatus.FAILED}:
            row.completed_at = datetime.utcnow()
        session.commit()

    def _merge_extra_data_sync(self, job_id: str, **fields) -> None:
        if not fields:
            return
        session = self._session()
        row = session.query(ImageJobTable).filter(ImageJobTable.id == job_id).first()
        if row is None:
            return
        merged = dict(row.extra_data or {})
        for key, value in fields.items():
            if value is not None:
                merged[key] = value
        row.extra_data = merged
        session.commit()

    def _record_to_model(self, record: dict) -> ImageJob:
        output = ImageJobOutput(**record["output"]) if record.get("output") else None
        return ImageJob(
            id=record["id"],
            provider_key=record["provider_key"],
            provider_job_id=record.get("provider_job_id"),
            status=ImageJobStatus(record["status"]),
            input=ImageJobInput(
                prompt=record["prompt"],
                mode=record["mode"],
                references=[ImageReference(**ref) for ref in (record.get("references") or [])],
                mask_url=record.get("mask_url"),
                size=record.get("size") or "1024x1024",
                quality=record.get("quality") or "high",
                metadata=record.get("extra_data") or {},
            ),
            output=output,
            error=record.get("error"),
            created_at=record.get("created_at") or datetime.utcnow(),
            started_at=record.get("started_at"),
            completed_at=record.get("completed_at"),
        )

    def _resolve_request(self, provider_key: str, request: ImageJobInput) -> tuple[str, ImageJobInput]:
        """Apply workflow defaults when workflow_id is present in metadata."""
        workflow_id = request.metadata.get("workflow_id")
        if not workflow_id:
            return provider_key, request
        try:
            workflow = get_workflow(workflow_id)
        except ValueError:
            return provider_key, request
        merged_meta = apply_workflow_to_request(workflow, request.metadata)
        resolved_key = resolve_provider_key(workflow, provider_key)
        merged_meta["provider_key"] = resolved_key
        size = request.size
        if is_arena_request(request):
            # Both slots must share the caller's size; ignore per-workflow aspect defaults.
            merged_meta.pop("aspect", None)
        else:
            aspect = merged_meta.get("aspect")
            if aspect and isinstance(aspect, str) and ":" in aspect and "x" not in aspect:
                parts = aspect.split(":")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    w, h = int(parts[0]), int(parts[1])
                    base = 1024
                    size = f"{base}x{int(base * h / w)}" if w >= h else f"{int(base * w / h)}x{base}"
        return resolved_key, request.model_copy(update={"metadata": merged_meta, "size": size})

    async def submit(
        self,
        provider_key: str,
        request: ImageJobInput,
        *,
        progress_cb: ImageProgressCallback | None = None,
    ) -> ImageJob:
        provider_key, request = self._resolve_request(provider_key, request)
        provider = self._provider(provider_key)
        if progress_cb is not None and hasattr(provider, "bind_progress_callback"):
            provider.bind_progress_callback(progress_cb)
        with _tracer.start_as_current_span("image.submit") as span:
            span.set_attribute("image.provider_key", provider_key)
            span.set_attribute("image.mode", request.mode.value)
            if request.user_id:
                span.set_attribute("portal.user_id", request.user_id)
                span.set_attribute("discord.user_id", request.metadata.get("discord_user_id", request.user_id))
            try:
                from observability.boundary import emit_visibility, sync_stack_window

                sync_stack_window(span)
                emit_visibility(
                    "image.submit.start",
                    span=span,
                    boundary="image.service",
                    provider_key=provider_key,
                    mode=request.mode.value,
                )
            except ImportError:
                pass
            try:
                provider_job_id, status = await provider.submit(request)
            finally:
                if hasattr(provider, "clear_progress_callback"):
                    provider.clear_progress_callback()
            job_model = ImageJob(
                provider_key=provider_key,
                provider_job_id=provider_job_id,
                status=status,
                input=request,
                started_at=datetime.utcnow(),
            )
            span.set_attribute("image.job_id", job_model.id)
            span.set_attribute("fal.request_id", provider_job_id or "")
            self._memory_jobs[job_model.id] = job_model
            if status == ImageJobStatus.COMPLETED:
                await self._hydrate_sync_output(job_model, provider)

            trace_id = _current_trace_id()
            correlation = {
                "trace_id": trace_id,
                "fal_request_id": provider_job_id,
                "discord_interaction_id": request.metadata.get("discord_interaction_id"),
                "discord_message_id": request.metadata.get("discord_message_id"),
                "discord_user_id": request.metadata.get("discord_user_id"),
                "portal_user_id": request.user_id,
                "discord_channel_id": request.channel_id,
                "discord_guild_id": request.guild_id,
            }
            request.metadata.update({k: v for k, v in correlation.items() if v is not None})

            await self._db_op("image_job_persist", self._persist_job_sync, job_model)

            logger.info(
                "image_job_submitted",
                job_id=job_model.id,
                provider_key=provider_key,
                fal_request_id=provider_job_id,
                mode=request.mode.value,
                user_id=request.user_id,
                trace_id=trace_id,
            )
            try:
                from observability.boundary import emit_visibility

                emit_visibility(
                    "image.submit.done",
                    span=span,
                    boundary="image.service",
                    job_id=job_model.id,
                    provider_key=provider_key,
                    status=status.value,
                    provider_job_id=provider_job_id or "",
                )
            except ImportError:
                pass
            return job_model

    async def _hydrate_sync_output(self, job: ImageJob, provider) -> None:
        """Attach inline provider output for sync completions (e.g. ComfyUI graph)."""
        if job.status != ImageJobStatus.COMPLETED:
            return
        if job.output and job.output.outputs:
            return
        if not job.provider_job_id:
            return
        status, output, provider_error = await provider.poll(job.provider_job_id)
        if status == ImageJobStatus.COMPLETED and output:
            job.output = output
            job.completed_at = datetime.utcnow()
        elif status == ImageJobStatus.FAILED:
            job.status = ImageJobStatus.FAILED
            job.error = provider_error or "provider_failed"
            job.completed_at = datetime.utcnow()

    async def poll(self, job_id: str) -> ImageJob:
        cached = self._memory_jobs.get(job_id)
        if cached is not None:
            if cached.status == ImageJobStatus.FAILED:
                return cached
            if not cached.provider_job_id:
                return cached
            if cached.status == ImageJobStatus.COMPLETED and cached.output and cached.output.outputs:
                return cached

        row = None
        # Skip the blocking sync DB query when the job is already in memory.
        # With a stale schema the connection pool blocks the event loop indefinitely,
        # stalling Discord heartbeats and triggering gateway disconnects.
        if cached is None:
            try:
                row = await self._to_thread(self._load_job_record_sync, job_id)
            except SQLAlchemyError:
                row = None

        if row is None and cached is None:
            raise ValueError("Image job not found")

        provider_key = row["provider_key"] if row is not None else cached.provider_key
        provider_job_id = row["provider_job_id"] if row is not None else cached.provider_job_id
        provider = self._provider(provider_key)
        status, output, provider_error = await provider.poll(provider_job_id)

        if cached is not None:
            cached.status = status
        if row is not None:
            row["status"] = status.value

        if status == ImageJobStatus.COMPLETED and output:
            duration_ms = None
            if cached and cached.started_at:
                duration_ms = int((datetime.utcnow() - cached.started_at).total_seconds() * 1000)
            logger.info(
                "image_job_completed",
                job_id=job_id,
                provider_key=provider_key,
                duration_ms=duration_ms,
            )
            mirrored_outputs = []
            for output_item in output.outputs:
                try:
                    mirrored = await self._storage.mirror_url(output_item.url, subdir="outputs")
                    mirrored_outputs.append(mirrored)
                except Exception as exc:
                    logger.warning("image_output_mirror_failed", error=str(exc), url=output_item.url)
                    mirrored_outputs.append(output_item)
            updated_output = output.model_copy(update={"outputs": mirrored_outputs})
            if row is not None:
                row["output"] = updated_output.model_dump()
                row["completed_at"] = datetime.utcnow()
            await self._db_op(
                "image_job_update",
                self._persist_job_state_sync,
                job_id=job_id,
                status=status,
                output=updated_output,
            )
            if cached is not None:
                cached.output = updated_output
                cached.completed_at = datetime.utcnow()
            user_id = None
            if cached and cached.input:
                user_id = cached.input.user_id
            elif row is not None and row.get("extra_data"):
                user_id = (row.get("extra_data") or {}).get("portal_user_id")
            if user_id:
                from maya_image.portal.activity import emit_event_standalone

                await emit_event_standalone(
                    user_id=user_id,
                    kind="image.job_completed",
                    title="Image job completed",
                    body=(cached.input.prompt if cached else "")[:200],
                    source="image_service",
                    metadata={"job_id": job_id, "provider_key": provider_key},
                )
        elif status == ImageJobStatus.FAILED:
            error_msg = provider_error or "provider_failed"
            logger.error(
                "image_job_failed",
                job_id=job_id,
                provider_key=provider_key,
                error=error_msg,
                trace_id=_current_trace_id(),
            )
            if row is not None:
                row["error"] = error_msg
                row["completed_at"] = datetime.utcnow()
            await self._db_op(
                "image_job_update",
                self._persist_job_state_sync,
                job_id=job_id,
                status=status,
                error=error_msg,
            )
            await self._db_op(
                "image_job_extra_data_update",
                self._merge_extra_data_sync,
                job_id,
                fal_error=error_msg,
                failed_trace_id=_current_trace_id(),
            )
            if cached is not None:
                cached.error = error_msg
                cached.completed_at = datetime.utcnow()
        elif status not in {ImageJobStatus.COMPLETED, ImageJobStatus.FAILED}:
            await self._db_op(
                "image_job_update",
                self._persist_job_state_sync,
                job_id=job_id,
                status=status,
            )
        return cached or self._record_to_model(row)

    async def wait_for_job(
        self,
        job_id: str,
        *,
        max_polls: int = 180,
        poll_interval: float = 5.0,
        timeout_sec: float | None = None,
    ) -> ImageJob:
        wait_started = time.monotonic()
        if timeout_sec is not None:
            deadline = wait_started + timeout_sec
            attempt_limit: int | None = None
            timeout_label = f"{int(timeout_sec)}s"
        elif poll_interval > 0:
            deadline = wait_started + max_polls * poll_interval
            attempt_limit = None
            timeout_label = f"{int(max_polls * poll_interval)}s"
        else:
            deadline = float("inf")
            attempt_limit = max_polls
            timeout_label = f"{max_polls} poll attempts"

        job: ImageJob | None = None
        attempts = 0
        last_error: str | None = None

        def _timed_out() -> bool:
            if attempt_limit is not None and attempts >= attempt_limit:
                return True
            return time.monotonic() >= deadline

        with _tracer.start_as_current_span("image.wait_for_job") as wait_span:
            wait_span.set_attribute("image.job_id", job_id)
            wait_span.set_attribute("image.wait_timeout_sec", timeout_sec or 0)
            try:
                from observability.boundary import emit_visibility, sync_stack_window

                sync_stack_window(wait_span)
                emit_visibility(
                    "image.wait.start",
                    span=wait_span,
                    boundary="image.service",
                    job_id=job_id,
                    timeout_label=timeout_label,
                )
            except ImportError:
                pass

            while not _timed_out():
                attempts += 1
                try:
                    job = await self.poll(job_id)
                except Exception as exc:
                    last_error = str(exc)
                    logger.warning(
                        "image_job_poll_exception",
                        error=last_error,
                        job_id=job_id,
                        attempt=attempts,
                    )
                    try:
                        from observability.boundary import emit_visibility

                        emit_visibility(
                            "image.poll.error",
                            span=wait_span,
                            boundary="image.service",
                            job_id=job_id,
                            attempt=attempts,
                            error=last_error,
                        )
                    except ImportError:
                        pass
                    if _timed_out():
                        break
                    if poll_interval > 0:
                        await asyncio.sleep(
                            min(poll_interval, max(0.0, deadline - time.monotonic()))
                        )
                    continue
                try:
                    from observability.boundary import emit_visibility

                    emit_visibility(
                        "image.poll.tick",
                        span=wait_span,
                        boundary="image.service",
                        job_id=job_id,
                        attempt=attempts,
                        status=job.status.value,
                    )
                except ImportError:
                    pass
                if job.status in {ImageJobStatus.COMPLETED, ImageJobStatus.FAILED}:
                    wait_span.set_attribute("image.final_status", job.status.value)
                    return job
                if _timed_out():
                    break
                if poll_interval > 0:
                    await asyncio.sleep(
                        min(poll_interval, max(0.0, deadline - time.monotonic()))
                    )

            elapsed_ms = int((time.monotonic() - wait_started) * 1000)
            if job is None:
                try:
                    job = await self.poll(job_id)
                except Exception as exc:
                    last_error = str(exc)
            provider_key = job.provider_key if job else "unknown"
            logger.error(
                "image_job_wait_timeout",
                job_id=job_id,
                provider_key=provider_key,
                attempts=attempts,
                elapsed_ms=elapsed_ms,
                last_error=last_error,
                trace_id=_current_trace_id(),
            )
            try:
                from observability.boundary import emit_visibility

                emit_visibility(
                    "image.wait.timeout",
                    span=wait_span,
                    boundary="image.service",
                    job_id=job_id,
                    provider_key=provider_key,
                    attempts=attempts,
                    elapsed_ms=elapsed_ms,
                    last_error=last_error,
                )
            except ImportError:
                pass
            if job is not None and job.status not in {ImageJobStatus.COMPLETED, ImageJobStatus.FAILED}:
                job.status = ImageJobStatus.FAILED
                job.error = f"Image job timed out after {timeout_label}"
                job.completed_at = datetime.utcnow()
                self._memory_jobs[job_id] = job
            return job or ImageJob(
                id=job_id,
                provider_key=provider_key,
                status=ImageJobStatus.FAILED,
                input=ImageJobInput(prompt="timeout", mode=ImageMode.GENERATE),
                error=last_error or "image_job_wait_timeout",
                completed_at=datetime.utcnow(),
            )

    def _arena_pool_from_workflows(self) -> list[dict]:
        try:
            rows = list_arena_runnable_workflows(category="t2i")
        except Exception as exc:
            logger.warning("arena_workflow_pool_failed", error=str(exc))
            rows = []
        pool = []
        for wf in rows:
            pool.append(self._workflow_contender(wf))
        return pool

    def _workflow_contender(self, workflow) -> dict:
        provider_key = resolve_provider_key(workflow)
        provider = workflow.provider or (provider_key.split(":")[0] if provider_key else "unknown")
        model_key = workflow.params.get("model_key") or workflow.provider_key
        return {
            "provider_key": provider_key,
            "provider": provider,
            "model_key": model_key,
            "display_name": workflow.display_name,
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
        }

    _ARENA_LIGHT_WORKFLOW_NAMES = frozenset({"z-image-turbo-t2i"})
    _ARENA_HEAVY_WORKFLOW_NAMES = frozenset(
        {"krea2-turbo-t2i", "flux2-t2i", "comfyui-ideogram4-t2i"}
    )

    def _contender_from_pool(self, pool: list[dict], key: str) -> dict | None:
        for contender in pool:
            if contender.get("workflow_name") == key or contender.get("workflow_id") == key:
                return contender
        return None

    def _select_arena_contenders(self) -> tuple[dict, dict]:
        pool = self._arena_pool_from_workflows()
        if len(pool) < 2:
            raise RuntimeError("no arena-ready local workflows")
        if os.getenv("MAYA_ARENA_DETERMINISTIC"):
            return pool[0], pool[1]

        fixed_pair = arena_pair_from_env()
        if fixed_pair:
            a = self._contender_from_pool(pool, fixed_pair[0])
            b = self._contender_from_pool(pool, fixed_pair[1])
            if a and b and a["workflow_id"] != b["workflow_id"]:
                return a, b
            logger.warning(
                "arena_fixed_pair_unavailable",
                pair=fixed_pair,
                pool_names=[c.get("workflow_name") for c in pool],
            )

        light = [c for c in pool if c.get("workflow_name") in self._ARENA_LIGHT_WORKFLOW_NAMES]
        heavy = [c for c in pool if c.get("workflow_name") in self._ARENA_HEAVY_WORKFLOW_NAMES]
        if light and heavy:
            return random.choice(light), random.choice(heavy)
        if len(light) >= 2:
            return random.sample(light, 2)

        return random.sample(pool, 2)

    async def _submit_arena_slots(
        self,
        contender_a: dict,
        contender_b: dict,
        req_a: ImageJobInput,
        req_b: ImageJobInput,
    ) -> tuple[ImageJob, ImageJob]:
        """Submit arena slots; sequential by default to avoid single-GPU Comfy contention."""
        parallel = os.getenv("MAYA_ARENA_PARALLEL_SUBMIT", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if parallel:
            return await asyncio.gather(
                self._submit_arena_slot(contender_a["provider_key"], req_a),
                self._submit_arena_slot(contender_b["provider_key"], req_b),
            )
        job_a = await self._submit_arena_slot(contender_a["provider_key"], req_a)
        job_b = await self._submit_arena_slot(contender_b["provider_key"], req_b)
        return job_a, job_b

    async def _submit_arena_slot(self, provider_key: str, request: ImageJobInput) -> ImageJob:
        """Submit one arena slot; failures become a failed in-memory job instead of aborting."""
        try:
            return await self.submit(provider_key, request)
        except Exception as exc:
            logger.warning(
                "arena_slot_submit_failed",
                provider_key=provider_key,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            failed = ImageJob(
                provider_key=provider_key,
                status=ImageJobStatus.FAILED,
                input=request,
                error=str(exc),
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
            self._memory_jobs[failed.id] = failed
            return failed

    def _arena_jobs_for_interaction(self, request: ImageJobInput) -> dict[str, ImageJob]:
        interaction_id = request.metadata.get("discord_interaction_id")
        if not interaction_id:
            return {}
        slots: dict[str, ImageJob] = {}
        for job in self._memory_jobs.values():
            if job.input.mode != ImageMode.ARENA:
                continue
            if job.input.metadata.get("discord_interaction_id") != interaction_id:
                continue
            slot = job.input.metadata.get("arena_slot")
            if slot in {"a", "b"}:
                slots[slot] = job
        return slots

    async def salvage_inflight_arena(
        self,
        request: ImageJobInput,
        *,
        contender_labels: dict[str, str] | None = None,
    ) -> dict | None:
        """Build a battle shell from in-memory arena jobs after a hard timeout."""
        slots = self._arena_jobs_for_interaction(request)
        if not slots:
            return None
        if not any(
            job.status == ImageJobStatus.COMPLETED and job.output and job.output.outputs
            for job in slots.values()
        ):
            return None

        labels = dict(contender_labels or {})
        for slot, job in slots.items():
            if slot in labels:
                continue
            wf_id = job.input.metadata.get("workflow_id")
            if wf_id:
                try:
                    labels[slot] = get_workflow(wf_id).display_name
                except ValueError:
                    labels[slot] = job.provider_key
            else:
                labels[slot] = job.provider_key
        candidate_ids: dict[str, str] = {}
        for slot, job in slots.items():
            label = labels.get(slot) or job.provider_key
            candidate = await self._ensure_arena_candidate(
                modality="image",
                provider=job.provider_key.split(":")[0],
                model_key=label,
                display_name=label,
            )
            candidate_ids[slot] = candidate.id

        for slot in ("a", "b"):
            if slot in candidate_ids:
                continue
            candidate = await self._ensure_arena_candidate(
                modality="image",
                provider="unknown",
                model_key=f"arena-{slot}",
                display_name=labels.get(slot, slot.upper()),
            )
            candidate_ids[slot] = candidate.id

        input_payload = request.model_dump(mode="json")
        battle = await self._create_arena_battle(
            candidate_ids["a"],
            candidate_ids["b"],
            request.prompt,
            "arena_timeout_salvage",
            modality="image",
            input_payload=input_payload,
        )
        job_ids = {slot: job.id for slot, job in slots.items()}
        for slot in ("a", "b"):
            job_ids.setdefault(slot, "")
            if slot not in slots:
                failed = ImageJob(
                    provider_key="unknown",
                    status=ImageJobStatus.FAILED,
                    input=request.model_copy(
                        update={"metadata": {**request.metadata, "arena_slot": slot}}
                    ),
                    error="arena hard timeout before slot completed",
                    completed_at=datetime.utcnow(),
                )
                self._memory_jobs[failed.id] = failed
                job_ids[slot] = failed.id

        finalized = await self.finalize_arena_jobs(
            battle.id,
            job_ids,
            candidate_ids,
            max_polls=1,
            poll_interval=0,
            timeout_sec=1.0,
        )
        return {
            "battle_id": battle.id,
            "job_ids": job_ids,
            "candidate_ids": candidate_ids,
            "contender_labels": labels,
            **finalized,
        }

    async def submit_arena(self, request: ImageJobInput) -> dict:
        request = normalize_arena_resolution(request)
        request.metadata.setdefault("mode", request.mode.value)

        contender_a, contender_b = self._select_arena_contenders()
        req_a = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "workflow_id": contender_a.get("workflow_id"),
                    "arena_slot": "a",
                }
            }
        )
        req_b = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "workflow_id": contender_b.get("workflow_id"),
                    "arena_slot": "b",
                }
            }
        )
        job_a, job_b = await self._submit_arena_slots(contender_a, contender_b, req_a, req_b)

        candidate_a = await self._ensure_arena_candidate(
            modality="image",
            provider=contender_a["provider"],
            model_key=contender_a["model_key"],
            display_name=contender_a["display_name"],
        )
        candidate_b = await self._ensure_arena_candidate(
            modality="image",
            provider=contender_b["provider"],
            model_key=contender_b["model_key"],
            display_name=contender_b["display_name"],
        )
        battle = await self._create_arena_battle(
            candidate_a.id,
            candidate_b.id,
            request.prompt,
            "discord",
            modality="image",
            input_payload=request.model_dump(mode="json"),
        )
        return {
            "battle_id": battle.id,
            "job_ids": {"a": job_a.id, "b": job_b.id},
            "candidate_ids": {"a": candidate_a.id, "b": candidate_b.id},
            "contender_labels": {
                "a": contender_a["display_name"],
                "b": contender_b["display_name"],
            },
        }

    async def submit_workflow_arena(
        self,
        request: ImageJobInput,
        *,
        source_workflow_id: str | None = None,
    ) -> dict:
        """Pit a specific workflow against a random arena candidate (same prompt)."""
        request = normalize_arena_resolution(request)
        request.metadata.setdefault("mode", request.mode.value)

        source_id = source_workflow_id or request.metadata.get("workflow_id")
        if not source_id:
            return await self.submit_arena(request)

        source_wf = get_workflow(source_id)
        if not workflow_is_arena_runnable(source_wf):
            return await self.submit_arena(request)

        contender_a = self._workflow_contender(source_wf)
        pool = [
            w
            for w in list_arena_runnable_workflows(category="t2i")
            if w.id != source_wf.id
        ]
        if not pool:
            return await self.submit_arena(request)
        opponent_wf = random.choice(pool)
        logger.info(
            "arena_opponent_selected",
            source_workflow=source_wf.name,
            opponent_workflow=opponent_wf.name,
        )
        contender_b = self._workflow_contender(opponent_wf)

        req_a = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "workflow_id": contender_a["workflow_id"],
                    "arena_slot": "a",
                }
            }
        )
        req_b = request.model_copy(
            update={
                "metadata": {
                    **request.metadata,
                    "workflow_id": contender_b["workflow_id"],
                    "arena_slot": "b",
                }
            }
        )
        job_a, job_b = await self._submit_arena_slots(contender_a, contender_b, req_a, req_b)

        input_payload = request.model_dump(mode="json")
        input_payload["workflow_contenders"] = {
            "a": contender_a["workflow_id"],
            "b": contender_b["workflow_id"],
        }

        candidate_a = await self._ensure_arena_candidate(
            modality="image",
            provider=contender_a["provider"],
            model_key=contender_a["model_key"],
            display_name=contender_a["display_name"],
        )
        candidate_b = await self._ensure_arena_candidate(
            modality="image",
            provider=contender_b["provider"],
            model_key=contender_b["model_key"],
            display_name=contender_b["display_name"],
        )
        battle = await self._create_arena_battle(
            candidate_a.id,
            candidate_b.id,
            request.prompt,
            "workflow_arena",
            modality="image",
            input_payload=input_payload,
        )
        return {
            "battle_id": battle.id,
            "job_ids": {"a": job_a.id, "b": job_b.id},
            "candidate_ids": {"a": candidate_a.id, "b": candidate_b.id},
            "contender_labels": {
                "a": contender_a["display_name"],
                "b": contender_b["display_name"],
            },
            "workflow_contenders": input_payload["workflow_contenders"],
        }

    async def submit_named_workflow_battle(
        self,
        request: ImageJobInput,
        workflow_a_id: str,
        workflow_b_id: str,
    ) -> dict:
        """Run an arena battle between two named workflows (blocking — legacy callers)."""
        spec = await self.begin_named_workflow_battle(request, workflow_a_id, workflow_b_id)
        job_ids = await self.execute_battle_jobs(spec)
        return {
            "battle_id": spec["battle_id"],
            "job_ids": job_ids,
            "candidate_ids": spec["candidate_ids"],
            "contender_labels": spec["contender_labels"],
            "workflow_contenders": spec["workflow_contenders"],
        }

    async def begin_named_workflow_battle(
        self,
        request: ImageJobInput,
        workflow_a_id: str,
        workflow_b_id: str,
    ) -> dict:
        """Create battle shell with randomized slot assignment; jobs run via execute_battle_jobs."""
        request = normalize_arena_resolution(request)
        request.metadata.setdefault("mode", request.mode.value)

        wf_a = get_workflow(workflow_a_id)
        wf_b = get_workflow(workflow_b_id)
        info_a = self._workflow_contender(wf_a)
        info_b = self._workflow_contender(wf_b)

        # Randomize which workflow lands in slot a vs b (blind voting integrity).
        if random.random() < 0.5:
            slot_map = {"a": info_a, "b": info_b}
            wf_contenders = {"a": workflow_a_id, "b": workflow_b_id}
        else:
            slot_map = {"a": info_b, "b": info_a}
            wf_contenders = {"a": workflow_b_id, "b": workflow_a_id}

        input_payload = request.model_dump(mode="json")
        input_payload["workflow_contenders"] = wf_contenders

        candidate_ids: dict[str, str] = {}
        for slot, info in slot_map.items():
            cand = await self._ensure_arena_candidate(
                modality="image",
                provider=info["provider"],
                model_key=info["model_key"],
                display_name=info["display_name"],
            )
            candidate_ids[slot] = cand.id

        battle = await self._create_arena_battle(
            candidate_ids["a"],
            candidate_ids["b"],
            request.prompt,
            "workflow_battle",
            modality="image",
            input_payload=input_payload,
        )
        return {
            "battle_id": battle.id,
            "candidate_ids": candidate_ids,
            "slot_map": slot_map,
            "request": request,
            "contender_labels": {s: slot_map[s]["display_name"] for s in ("a", "b")},
            "workflow_contenders": wf_contenders,
        }

    async def begin_multi_workflow_battle(
        self,
        request: ImageJobInput,
        workflow_ids: list[str],
        *,
        randomize: bool = True,
        max_contenders: int | None = None,
    ) -> dict:
        """Create an N-contender battle (gateway studio); first two map to candidate_a/b."""
        cap = max_contenders if max_contenders is not None else arena_max_contenders(for_studio=True)
        ids = list(dict.fromkeys(workflow_ids))[:cap]
        if len(ids) < 2:
            raise ValueError("Need at least 2 distinct workflows for multi battle")

        with _tracer.start_as_current_span("image.arena.begin_multi") as span:
            span.set_attribute("image.arena.contender_count", len(ids))
            trace_id = _current_trace_id()
            if trace_id:
                span.set_attribute("trace_id", trace_id)

            request = normalize_arena_resolution(request)
            request.metadata.setdefault("mode", request.mode.value)

            if randomize:
                random.shuffle(ids)

            slot_names = _arena_slot_names(len(ids))
            slot_map: dict[str, dict] = {}
            wf_contenders: dict[str, str] = {}
            for slot, wf_id in zip(slot_names, ids):
                wf = get_workflow(wf_id)
                slot_map[slot] = self._workflow_contender(wf)
                wf_contenders[slot] = wf_id

            input_payload = request.model_dump(mode="json")
            input_payload["workflow_contenders"] = wf_contenders
            if trace_id:
                input_payload["trace_id"] = trace_id

            candidate_ids: dict[str, str] = {}
            for slot, info in slot_map.items():
                cand = await self._ensure_arena_candidate(
                    modality="image",
                    provider=info["provider"],
                    model_key=info["model_key"],
                    display_name=info["display_name"],
                )
                candidate_ids[slot] = cand.id

            input_payload["candidate_ids"] = candidate_ids
            if len(slot_names) > 2:
                input_payload["extra_candidates"] = {
                    s: candidate_ids[s] for s in slot_names[2:]
                }

            battle = await self._create_arena_battle(
                candidate_ids["a"],
                candidate_ids["b"],
                request.prompt,
                "multi_workflow_battle",
                modality="image",
                input_payload=input_payload,
            )
            span.set_attribute("image.battle_id", battle.id)

            return {
                "battle_id": battle.id,
                "candidate_ids": candidate_ids,
                "slot_map": slot_map,
                "request": request,
                "contender_labels": {s: slot_map[s]["display_name"] for s in slot_names},
                "workflow_contenders": wf_contenders,
                "slots": slot_names,
            }

    async def execute_battle_jobs(self, spec: dict) -> dict[str, str]:
        """Submit generation jobs for all battle slots (may block on ComfyUI)."""
        request: ImageJobInput = spec["request"]
        slot_map = spec["slot_map"]
        job_ids: dict[str, str] = {}
        with _tracer.start_as_current_span("image.arena.execute_jobs") as span:
            span.set_attribute("image.battle_id", spec.get("battle_id", ""))
            span.set_attribute("image.arena.slot_count", len(slot_map))
            for slot, info in slot_map.items():
                req = request.model_copy(
                    update={
                        "metadata": {
                            **request.metadata,
                            "workflow_id": info["workflow_id"],
                            "arena_slot": slot,
                        }
                    }
                )
                job = await self.submit(info["provider_key"], req)
                job_ids[slot] = job.id
                span.set_attribute(f"image.job_id.{slot}", job.id)
        return job_ids

    async def finalize_arena_jobs(
        self,
        battle_id: str,
        job_ids: dict[str, str],
        candidate_ids: dict[str, str],
        *,
        max_polls: int = 180,
        poll_interval: float = 5.0,
        timeout_sec: float | None = None,
    ) -> dict:
        if timeout_sec is not None:
            slot_timeout = timeout_sec
        elif poll_interval > 0:
            slot_timeout = max_polls * poll_interval
        else:
            slot_timeout = None

        async def _wait_for_slot(slot: str) -> ImageJob:
            return await self.wait_for_job(
                job_ids[slot],
                max_polls=max_polls,
                poll_interval=poll_interval,
                timeout_sec=slot_timeout,
            )

        logger.info("arena_finalize_started", battle_id=battle_id)
        slots = list(job_ids.keys())
        with _tracer.start_as_current_span("image.arena.finalize") as span:
            span.set_attribute("image.battle_id", battle_id)
            span.set_attribute("image.arena.slot_count", len(slots))
            results = dict(
                zip(slots, await asyncio.gather(*(_wait_for_slot(slot) for slot in slots)))
            )

        for slot, job in results.items():
            if job.output:
                first = job.output.outputs[0]
                await self._db_op(
                    "arena.add_artifact",
                    self._arena.add_artifact,
                    battle_id=battle_id,
                    candidate_id=candidate_ids[slot],
                    slot=slot,
                    artifact_type="image",
                    url=first.url,
                    local_path=first.local_path,
                    mime_type=first.mime_type,
                    metadata=job.output.model_dump(),
                )

        logger.info(
            "arena_finalize_completed",
            battle_id=battle_id,
            **{f"slot_{slot}_status": results[slot].status.value for slot in slots if results.get(slot)},
        )

        for slot, job in results.items():
            if job and job.status == ImageJobStatus.FAILED and "content_policy_violation" in (job.error or ""):
                await self._db_op(
                    "arena.forfeit_battle",
                    self._arena.forfeit_battle,
                    battle_id,
                    candidate_ids[slot],
                    "content_policy",
                )

        for job_id in job_ids.values():
            self._memory_jobs.pop(job_id, None)
        return results

    async def ensure_local_output(self, output: ImageOutput, *, subdir: str = "outputs") -> ImageOutput:
        if output.local_path and Path(output.local_path).exists():
            return output
        mirrored = await self._storage.mirror_url(output.url, subdir=subdir, mime_type=output.mime_type)
        return output.model_copy(update={"local_path": mirrored.local_path, "mime_type": mirrored.mime_type})

    def stage_reference(
        self,
        *,
        data: bytes,
        filename: str,
        mime_type: Optional[str] = None,
    ) -> ImageReference:
        local_path = self._storage.write_bytes(data, filename=filename, subdir="inputs")
        return ImageReference(source_url=local_path, filename=filename, mime_type=mime_type, local_path=local_path)

    async def upload_reference(self, reference: ImageReference, provider_key: str = "fal:gpt-image-2") -> ImageReference:
        provider = self._provider(provider_key)
        source_path = reference.local_path or reference.source_url
        if source_path.startswith("http://") or source_path.startswith("https://"):
            return reference
        uploaded_url = await provider.upload_file(source_path)
        return reference.model_copy(update={"source_url": uploaded_url})

    def _to_model(self, row: ImageJobTable) -> ImageJob:
        output = ImageJobOutput(**row.output) if row.output else None
        return ImageJob(
            id=row.id,
            provider_key=row.provider_key,
            provider_job_id=row.provider_job_id,
            status=ImageJobStatus(row.status),
            input=ImageJobInput(
                prompt=row.prompt,
                mode=row.mode,
                references=[ImageReference(**ref) for ref in (row.references or [])],
                mask_url=row.mask_url,
                size=row.size or "1024x1024",
                quality=row.quality or "high",
                metadata=row.extra_data or {},
            ),
            output=output,
            error=row.error,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )


_service: Optional[ImageJobService] = None


def get_image_service() -> ImageJobService:
    global _service
    if _service is None:
        _service = ImageJobService()
    return _service
