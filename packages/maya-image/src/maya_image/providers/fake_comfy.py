"""Fake ComfyUI graph provider for CI — instant completed jobs with placeholder images."""

from __future__ import annotations

import uuid
from typing import Optional

from maya_image.storage import ImageStorage
from maya_image.types.image_job import ImageJobInput, ImageJobOutput, ImageJobStatus, ImageOutput


class FakeComfyGraphProvider:
    """Returns immediately with a tiny on-disk PNG — no GPU required."""

    provider_key = "comfyui:graph"
    model_key = "fake"

    def __init__(self) -> None:
        self._results: dict[str, ImageJobOutput] = {}
        self._storage = ImageStorage()

    async def submit(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        job_id = f"fake-comfy-{uuid.uuid4().hex}"
        # 1x1 PNG bytes
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
        local_path = self._storage.write_bytes(png, filename=f"{job_id}.png", subdir="outputs")
        rel = local_path.split("outputs")[-1].lstrip("/\\")
        url = f"/imagine-outputs/outputs/{rel}" if "outputs" in local_path else f"/imagine-outputs/{job_id}.png"
        self._results[job_id] = ImageJobOutput(
            provider=self.provider_key,
            model=request.metadata.get("model_key", "fake"),
            outputs=[ImageOutput(url=url, local_path=local_path, mime_type="image/png")],
        )
        return job_id, ImageJobStatus.COMPLETED

    async def poll(
        self, provider_job_id: str
    ) -> tuple[ImageJobStatus, Optional[ImageJobOutput], Optional[str]]:
        cached = getattr(self, "_results", {}).get(provider_job_id)
        if cached:
            return ImageJobStatus.COMPLETED, cached, None
        return ImageJobStatus.FAILED, None, "unknown fake job"
