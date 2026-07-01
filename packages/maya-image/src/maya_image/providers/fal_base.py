"""fal-backed image provider base."""

from __future__ import annotations

import asyncio
import re
import os
from typing import Any, Optional

import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from maya_image.base import BaseImageProvider, ImageProviderError
from maya_image.types.image_job import ImageJobInput, ImageJobOutput, ImageJobStatus, ImageOutput

logger = structlog.get_logger()

try:
    from observability import get_tracer as _get_tracer
    _tracer = _get_tracer("image.fal")
except Exception:
    _tracer = trace.get_tracer("image.fal")


class FalBaseImageProvider(BaseImageProvider):
    endpoint_id: str = ""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key=api_key or os.getenv("FAL_KEY"))
        self._client = None
        self._handles: dict[str, Any] = {}

    @property
    def provider_key(self) -> str:
        return "fal"

    def _client_or_raise(self):
        if self._client is None:
            try:
                from fal_client import AsyncClient
            except ImportError as exc:
                raise ImageProviderError("fal-client is required for fal image providers") from exc
            self._client = AsyncClient(key=self.api_key)
        return self._client

    async def upload_file(self, path: str) -> str:
        with _tracer.start_as_current_span("fal.upload") as span:
            span.set_attribute("fal.endpoint", self.endpoint_id)
            span.set_attribute("file.path", path)
            try:
                client = self._client_or_raise()
                return await client.upload_file(path)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
                raise

    async def submit(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        with _tracer.start_as_current_span("fal.submit") as span:
            span.set_attribute("fal.endpoint", self.endpoint_id)
            span.set_attribute("fal.model", self.model_key)
            span.set_attribute("image.mode", request.mode.value)
            span.set_attribute("image.prompt_length", len(request.prompt))
            span.set_attribute("image.size", request.size or "")
            try:
                client = self._client_or_raise()
                payload = self.build_payload(request)
                endpoint = self._resolve_endpoint(request) if hasattr(self, "_resolve_endpoint") else self.endpoint_id
                handle = await client.submit(endpoint, arguments=payload)
                self._handles[handle.request_id] = handle
                span.set_attribute("fal.request_id", handle.request_id)
                return handle.request_id, ImageJobStatus.SUBMITTED
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
                raise

    async def poll(self, provider_job_id: str) -> tuple[ImageJobStatus, Optional[ImageJobOutput]]:
        with _tracer.start_as_current_span("fal.poll") as span:
            span.set_attribute("fal.endpoint", self.endpoint_id)
            span.set_attribute("fal.model", self.model_key)
            span.set_attribute("fal.request_id", provider_job_id)
            try:
                client = self._client_or_raise()
                handle = self._handles.get(provider_job_id)
                if handle is None:
                    from fal_client import AsyncRequestHandle
                    handle = AsyncRequestHandle.from_request_id(client, self.endpoint_id, provider_job_id)
                    self._handles[provider_job_id] = handle

                status = None
                last_exc: Optional[BaseException] = None
                for attempt in range(3):
                    try:
                        status = await handle.status(with_logs=True)
                        last_exc = None
                        break
                    except Exception as exc:
                        last_exc = exc
                        logger.warning(
                            "fal_status_transient_error",
                            error=str(exc),
                            attempt=attempt + 1,
                            provider=self.provider_key,
                            model=self.model_key,
                            request_id=provider_job_id,
                        )
                        if attempt < 2:
                            await asyncio.sleep(1.0 * (attempt + 1))
                if status is None:
                    span.set_attribute("fal.status", "transient_error")
                    if last_exc is not None:
                        span.record_exception(last_exc)
                    return ImageJobStatus.PROCESSING, None, None

                status_name = status.__class__.__name__.lower()
                if status_name in {"completed"}:
                    try:
                        result = await handle.get()
                    except Exception as exc:
                        error_str = str(exc)
                        is_policy = "content_policy_violation" in error_str
                        logger.warning(
                            "fal_content_policy_violation" if is_policy else "fal_result_fetch_failed",
                            error=error_str,
                            provider=self.provider_key,
                            model=self.model_key,
                            request_id=provider_job_id,
                            content_policy=is_policy,
                        )
                        span.record_exception(exc)
                        span.set_status(StatusCode.ERROR, error_str)
                        return ImageJobStatus.FAILED, None, error_str
                    output = self.normalize_output(result)
                    span.set_attribute("fal.status", "completed")
                    span.set_attribute("fal.output_count", len(output.outputs))
                    return ImageJobStatus.COMPLETED, output, None
                if status_name in {"failed", "errored", "error"}:
                    span.set_attribute("fal.status", "failed")
                    span.set_status(StatusCode.ERROR, "fal job failed")
                    return ImageJobStatus.FAILED, None, "provider_failed"
                span.set_attribute("fal.status", "processing")
                span.set_attribute("fal.status_class", status_name)
                return ImageJobStatus.PROCESSING, None, None
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
                raise

    async def cancel(self, provider_job_id: str) -> bool:
        handle = self._handles.get(provider_job_id)
        if handle is None:
            return False
        await handle.cancel()
        return True

    def normalize_output(self, payload: dict[str, Any]) -> ImageJobOutput:
        images = payload.get("images", []) or payload.get("data", {}).get("images", [])
        outputs = [
            ImageOutput(
                url=image.get("url") or image.get("image") or image.get("source_url"),
                mime_type=image.get("content_type"),
                width=image.get("width"),
                height=image.get("height"),
            )
            for image in images
            if image.get("url") or image.get("image") or image.get("source_url")
        ]
        return ImageJobOutput(
            provider=self.provider_key,
            model=self.model_key,
            outputs=outputs,
            revised_prompt=payload.get("revised_prompt"),
            raw_response=payload,
        )

    def build_payload(self, request: ImageJobInput) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int] | None:
        match = re.fullmatch(r"(\d+)x(\d+)", size.strip().lower())
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

    @classmethod
    def _size_to_image_size(cls, size: str) -> str | dict[str, int]:
        if size in {"auto", "square_hd", "square", "portrait_4_3", "portrait_16_9", "landscape_4_3", "landscape_16_9"}:
            return size
        parsed = cls._parse_size(size)
        if parsed is None:
            return "auto"
        width, height = parsed
        preset_map = {
            (1024, 1024): "square_hd",
            (512, 512): "square",
            (768, 1024): "portrait_4_3",
            (576, 1024): "portrait_16_9",
            (1024, 768): "landscape_4_3",
            (1024, 576): "landscape_16_9",
        }
        return preset_map.get((width, height), {"width": width, "height": height})

    @classmethod
    def _size_to_aspect_ratio(cls, size: str) -> str:
        if size == "auto":
            return "auto"
        parsed = cls._parse_size(size)
        if parsed is None:
            return "auto"
        width, height = parsed
        ratio = width / height if height else 1.0
        candidates = [
            ("1:1", 1.0),
            ("4:3", 4 / 3),
            ("3:2", 3 / 2),
            ("16:9", 16 / 9),
            ("5:4", 5 / 4),
            ("4:5", 4 / 5),
            ("3:4", 3 / 4),
            ("2:3", 2 / 3),
            ("9:16", 9 / 16),
            ("21:9", 21 / 9),
        ]
        return min(candidates, key=lambda item: abs(item[1] - ratio))[0]

    @classmethod
    def _size_to_resolution(cls, size: str) -> str:
        parsed = cls._parse_size(size)
        if parsed is None:
            return "1K"
        width, height = parsed
        longest = max(width, height)
        if longest >= 3200:
            return "4K"
        if longest >= 1600:
            return "2K"
        return "1K"
