"""Base image provider abstractions."""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Optional

import structlog

from maya_image.types.image_job import ImageJobInput, ImageJobOutput, ImageJobStatus

logger = structlog.get_logger()


class ImageError(Exception):
    """Base exception for image provider failures."""


class ImageProviderError(ImageError):
    """Provider transport or backend error."""


class BaseImageProvider(ABC):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("IMAGE_API_KEY", "")

    @property
    @abstractmethod
    def provider_key(self) -> str:
        """Stable provider identifier."""

    @property
    @abstractmethod
    def model_key(self) -> str:
        """Stable model identifier."""

    @abstractmethod
    async def submit(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        """Submit an image request and return provider job id + initial status."""

    @abstractmethod
    async def poll(self, provider_job_id: str) -> tuple[ImageJobStatus, Optional[ImageJobOutput], Optional[str]]:
        """Poll a provider job. Returns (status, output, error_message)."""

    async def cancel(self, provider_job_id: str) -> bool:
        return False

    async def wait_for_result(
        self,
        provider_job_id: str,
        *,
        max_attempts: int = 120,
        interval_seconds: float = 2.0,
    ) -> ImageJobOutput:
        for attempt in range(max_attempts):
            status, result, _ = await self.poll(provider_job_id)
            if status == ImageJobStatus.COMPLETED and result:
                return result
            if status == ImageJobStatus.FAILED:
                raise ImageProviderError(f"{self.provider_key} job failed: {provider_job_id}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(interval_seconds)
        raise ImageProviderError(f"{self.provider_key} job timed out: {provider_job_id}")

