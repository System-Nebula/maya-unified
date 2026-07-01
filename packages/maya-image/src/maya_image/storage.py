"""Storage helpers for image inputs and outputs."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import structlog

from maya_image.types.image_job import ImageOutput

logger = structlog.get_logger()

DEFAULT_ROOT = Path(os.getenv("MAYA_IMAGE_ROOT", "data/outputs/maya-image"))


class ImageStorage:
    def __init__(self, root: Optional[Path] = None):
        self.root = root or DEFAULT_ROOT

    def _target_dir(self, subdir: str) -> Path:
        target = self.root / subdir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def write_bytes(self, data: bytes, *, filename: Optional[str] = None, subdir: str = "inputs") -> str:
        name = filename or f"{uuid.uuid4().hex}.bin"
        path = self._target_dir(subdir) / name
        path.write_bytes(data)
        return str(path)

    async def mirror_url(
        self,
        url: str,
        *,
        filename: Optional[str] = None,
        subdir: str = "outputs",
        mime_type: Optional[str] = None,
    ) -> ImageOutput:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.read()
                content_type = mime_type or response.headers.get("Content-Type")
        file_name = filename or url.rstrip("/").split("/")[-1] or f"{uuid.uuid4().hex}.bin"
        local_path = self.write_bytes(data, filename=file_name, subdir=subdir)
        return ImageOutput(url=url, local_path=local_path, mime_type=content_type)

