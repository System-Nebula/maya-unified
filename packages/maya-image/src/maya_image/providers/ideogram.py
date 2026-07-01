"""Composite Ideogram 4.0 provider: direct API → fal → comfyui-api fallback chain.

Tier 1: Ideogram direct API ``/generate/v4`` (sync; cached for :meth:`poll`).
Tier 2: :class:`FalIdeogramProvider` when tier 1 fails.
Tier 3: :class:`ComfyUIIdeogramProvider` when tier 2 fails and ``COMFYUI_API_URL``
is set (opt-in by environment).

Reference-based edits try the direct ``/remix/v4`` API when a local staged
reference is available; otherwise fal remix, then comfyui for generate-only.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog
from opentelemetry import trace

from maya_image.base import BaseImageProvider
from maya_image.prompt_builders.ideogram import IdeogramPromptBuilder
from maya_image.providers.comfyui_ideogram import ComfyUIIdeogramProvider
from maya_image.providers.fal_ideogram import FalIdeogramProvider
from maya_image.providers.ideogram_api import IdeogramAPIClient, IdeogramAPIError
from maya_image.types.image_job import (
    ImageJobInput,
    ImageJobOutput,
    ImageJobStatus,
    ImageOutput,
)

logger = structlog.get_logger()
_tracer = trace.get_tracer("image.ideogram")

_DIRECT_PREFIX = "ideogram-direct-"


class IdeogramProvider(BaseImageProvider):
    """Ideogram 4.0 with a direct-API-first, fal-fallback chain."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        client: Optional[IdeogramAPIClient] = None,
        fal_provider: Optional[FalIdeogramProvider] = None,
        comfyui_provider: Optional[ComfyUIIdeogramProvider] = None,
    ):
        super().__init__(api_key=api_key)
        self._client = client or IdeogramAPIClient(api_key=api_key)
        self._prompt_builder = IdeogramPromptBuilder(api_client=self._client)
        self._fal = fal_provider or FalIdeogramProvider()
        if comfyui_provider is not None:
            self._comfyui = comfyui_provider
        elif os.getenv("COMFYUI_API_URL"):
            self._comfyui = ComfyUIIdeogramProvider()
        else:
            self._comfyui = None
        # job_id -> cached output for the synchronous direct path
        self._direct_results: dict[str, ImageJobOutput] = {}
        # provider_job_id -> "direct" | "fal" | "comfyui"
        self._routing: dict[str, str] = {}

    @property
    def provider_key(self) -> str:
        return "ideogram"

    @property
    def model_key(self) -> str:
        return "ideogram/4.0"

    def normalize_output(self, payload: dict[str, Any]) -> ImageJobOutput:
        data = payload.get("data") or payload.get("images") or []
        outputs = [
            ImageOutput(
                url=item.get("url") or item.get("image_url"),
                mime_type=item.get("content_type"),
                width=item.get("width"),
                height=item.get("height"),
            )
            for item in data
            if item.get("url") or item.get("image_url")
        ]
        revised = data[0].get("prompt") if data else None
        return ImageJobOutput(
            provider=self.provider_key,
            model=self.model_key,
            outputs=outputs,
            revised_prompt=revised,
            raw_response=payload,
        )

    async def _expand_prompt(self, request: ImageJobInput) -> str:
        if not request.metadata.get("expand_prompt", True):
            return request.prompt
        path = request.metadata.get("prompt_builder_path", "api")
        try:
            return await self._prompt_builder.build(request.prompt, path=path)
        except Exception as exc:
            logger.warning("ideogram_prompt_expand_failed", error=str(exc))
            return request.prompt

    async def submit(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        if request.references or request.mask_url:
            return await self._submit_edit(request)

        prompt = await self._expand_prompt(request)
        expanded = request.model_copy(update={"prompt": prompt})

        with _tracer.start_as_current_span("ideogram.submit") as span:
            span.set_attribute("image.mode", request.mode.value)
            try:
                payload = await self._client.generate(
                    expanded.prompt,
                    aspect_ratio=_aspect_ratio_enum(expanded.size),
                    magic_prompt_option=expanded.metadata.get("magic_prompt_option", "AUTO"),
                    seed=expanded.metadata.get("seed"),
                )
                output = self.normalize_output(payload)
                if not output.outputs:
                    raise IdeogramAPIError("ideogram returned no images")
                job_id = f"{_DIRECT_PREFIX}{uuid.uuid4().hex}"
                self._direct_results[job_id] = output
                self._routing[job_id] = "direct"
                span.set_attribute("ideogram.path", "direct")
                span.set_attribute("ideogram.output_count", len(output.outputs))
                return job_id, ImageJobStatus.COMPLETED
            except Exception as exc:
                logger.warning(
                    "ideogram_direct_failed_falling_back",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                span.set_attribute("ideogram.path", "fal_fallback")
                span.record_exception(exc)
                return await self._submit_fal(expanded)

    async def _submit_edit(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        """Try direct remix with local bytes, then fal."""
        if request.mask_url:
            return await self._submit_fal(request)

        ref = request.references[0] if request.references else None
        local_path = (ref.local_path or ref.source_url) if ref else None
        if local_path and not local_path.startswith(("http://", "https://")):
            path = Path(local_path)
            if path.exists():
                prompt = await self._expand_prompt(request)
                try:
                    image_bytes = path.read_bytes()
                    payload = await self._client.remix(
                        image_bytes,
                        prompt,
                        filename=ref.filename or path.name,
                        image_weight=int(request.metadata.get("image_weight", 50)),
                        aspect_ratio=_aspect_ratio_enum(request.size),
                    )
                    output = self.normalize_output(payload)
                    if output.outputs:
                        job_id = f"{_DIRECT_PREFIX}{uuid.uuid4().hex}"
                        self._direct_results[job_id] = output
                        self._routing[job_id] = "direct"
                        return job_id, ImageJobStatus.COMPLETED
                except Exception as exc:
                    logger.warning("ideogram_direct_remix_failed", error=str(exc))
        return await self._submit_fal(request)

    async def _submit_fal(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        try:
            provider_job_id, status = await self._fal.submit(request)
            self._routing[provider_job_id] = "fal"
            return provider_job_id, status
        except Exception as exc:
            logger.warning(
                "ideogram_fal_failed_falling_back",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return await self._submit_comfyui(request)

    async def _submit_comfyui(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        if self._comfyui is None:
            raise RuntimeError("all ideogram compute tiers exhausted")
        try:
            provider_job_id, status = await self._comfyui.submit(request)
            self._routing[provider_job_id] = "comfyui"
            return provider_job_id, status
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise RuntimeError("Local Ideogram workflow is not deployed on comfyui-api") from exc
            raise RuntimeError("all ideogram compute tiers exhausted") from exc
        except RuntimeError:
            raise RuntimeError("all ideogram compute tiers exhausted") from None

    async def poll(
        self, provider_job_id: str
    ) -> tuple[ImageJobStatus, Optional[ImageJobOutput], Optional[str]]:
        if provider_job_id in self._direct_results:
            return ImageJobStatus.COMPLETED, self._direct_results[provider_job_id], None
        route = self._routing.get(provider_job_id)
        if route == "comfyui" and self._comfyui is not None:
            return await self._comfyui.poll(provider_job_id)
        if route == "fal" or (
            route is None and not provider_job_id.startswith(_DIRECT_PREFIX)
        ):
            return await self._fal.poll(provider_job_id)
        # Direct id we no longer have cached (e.g. after a restart) — nothing to fetch.
        return ImageJobStatus.FAILED, None, "ideogram_direct_result_expired"

    async def upload_file(self, path: str) -> str:
        # Keep local path for direct remix; fal accepts URLs only.
        if Path(path).exists():
            return path
        return await self._fal.upload_file(path)

    async def describe(self, image_url: str) -> str:
        return await self._client.describe(image_url)

    async def cancel(self, provider_job_id: str) -> bool:
        if provider_job_id in self._direct_results:
            self._direct_results.pop(provider_job_id, None)
            return True
        if self._routing.get(provider_job_id) == "comfyui" and self._comfyui is not None:
            return await self._comfyui.cancel(provider_job_id)
        return await self._fal.cancel(provider_job_id)


def _aspect_ratio_enum(size: str) -> str:
    """Map a ``WIDTHxHEIGHT`` size to an Ideogram ASPECT_* enum value."""
    ratio = FalIdeogramProvider._size_to_aspect_ratio(size)
    mapping = {
        "1:1": "ASPECT_1_1",
        "16:9": "ASPECT_16_9",
        "9:16": "ASPECT_9_16",
        "4:3": "ASPECT_4_3",
        "3:4": "ASPECT_3_4",
        "3:2": "ASPECT_3_2",
        "2:3": "ASPECT_2_3",
        "10:16": "ASPECT_10_16",
        "16:10": "ASPECT_16_10",
    }
    return mapping.get(ratio, "ASPECT_1_1")
