"""Tier 3: self-hosted Ideogram 4 via comfyui-api (SaladTechnologies wrapper).

Calls ``POST /workflow/*`` and ``webhook_v2`` only — never ComfyUI :8188.
Vault recipes: typed-workflow-endpoints-over-raw-prompt, webhook-v2-signed-async-completion,
per-request-credential-broker, readiness-gated-horizontal-routing, storage-async-artifact-handoff.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

import httpx
import structlog

from maya_image.base import BaseImageProvider, ImageProviderError
from maya_image.providers.comfyui_job_registry import get_record, register_submitted
from maya_image.providers.fal_ideogram import FalIdeogramProvider
from maya_image.types.image_job import ImageJobInput, ImageJobOutput, ImageJobStatus, ImageOutput

logger = structlog.get_logger()

_DEFAULT_WORKFLOW = "ideogram4-t2i"
_COMFYUI_API_BASE = os.getenv("COMFYUI_API_URL", "http://localhost:3000")


def resolve_hf_token() -> str | None:
    return os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")


class ComfyUIIdeogramProvider(BaseImageProvider):
    """Self-hosted Ideogram 4 through comfyui-api typed workflow endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        workflow_path: str = _DEFAULT_WORKFLOW,
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        super().__init__()
        self._base = (base_url or _COMFYUI_API_BASE).rstrip("/")
        self._workflow_path = workflow_path.lstrip("/")
        self._webhook_url = webhook_url or os.getenv("MAYA_COMFYUI_WEBHOOK_URL")
        self._client = client
        self._owns_client = client is None

    @property
    def provider_key(self) -> str:
        return "comfyui:ideogram"

    @property
    def model_key(self) -> str:
        return "ideogram/4.0-local"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base, timeout=180.0)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def is_ready(self) -> bool:
        """Readiness-gated routing: /ready means warm and under queue depth cap."""
        try:
            client = await self._get_client()
            resp = await client.get("/ready", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    def _build_workflow_input(self, request: ImageJobInput) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "aspect_ratio": FalIdeogramProvider._size_to_aspect_ratio(request.size),
        }
        seed = request.metadata.get("seed")
        if seed is not None:
            payload["seed"] = seed
        return payload

    def _build_credentials(self) -> list[dict[str, Any]] | None:
        token = resolve_hf_token()
        if not token:
            return None
        return [
            {
                "url_pattern": "https://huggingface.co/**",
                "auth": {"type": "bearer", "token": token},
            }
        ]

    def normalize_completion(self, data: dict[str, Any]) -> ImageJobOutput:
        outputs: list[ImageOutput] = []
        for item in data.get("images") or []:
            if isinstance(item, str):
                if item.startswith("http://") or item.startswith("https://"):
                    outputs.append(ImageOutput(url=item))
                elif item.startswith("s3://"):
                    outputs.append(ImageOutput(url=item))
                else:
                    # base64 PNG from sync path — data URL for downstream mirror step
                    outputs.append(ImageOutput(url=f"data:image/png;base64,{item}"))
        return ImageJobOutput(
            provider=self.provider_key,
            model=self.model_key,
            outputs=outputs,
            revised_prompt=data.get("revised_prompt"),
            raw_response=data,
        )

    async def submit(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        if not await self.is_ready():
            raise RuntimeError("comfyui-api not ready — tier 3 unavailable")

        client = await self._get_client()
        comfyui_id = str(uuid.uuid4())
        body: dict[str, Any] = {
            "id": comfyui_id,
            "input": self._build_workflow_input(request),
        }
        credentials = self._build_credentials()
        if credentials:
            body["credentials"] = credentials
        if self._webhook_url:
            body["webhook_v2"] = self._webhook_url

        resp = await client.post(f"/workflow/{self._workflow_path}", json=body)
        resp.raise_for_status()
        data = resp.json()

        if resp.status_code == 202 or self._webhook_url:
            await register_submitted(comfyui_id)
            return comfyui_id, ImageJobStatus.SUBMITTED

        output = self.normalize_completion(data)
        if not output.outputs:
            raise ImageProviderError("comfyui-api returned no images")
        await register_submitted(comfyui_id)
        from maya_image.providers.comfyui_job_registry import register_completion

        await register_completion(comfyui_id, data)
        return comfyui_id, ImageJobStatus.COMPLETED

    async def poll(
        self, provider_job_id: str
    ) -> tuple[ImageJobStatus, Optional[ImageJobOutput], Optional[str]]:
        record = await get_record(provider_job_id)
        if record is None:
            return ImageJobStatus.SUBMITTED, None, None
        if record.status == "completed" and record.payload:
            return (
                ImageJobStatus.COMPLETED,
                self.normalize_completion(record.payload),
                None,
            )
        if record.status == "failed":
            return ImageJobStatus.FAILED, None, record.error or "comfyui_job_failed"
        return ImageJobStatus.SUBMITTED, None, None

    async def cancel(self, provider_job_id: str) -> bool:
        try:
            client = await self._get_client()
            resp = await client.post("/interrupt", json={"id": provider_job_id})
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("comfyui_interrupt_failed", id=provider_job_id, error=str(exc))
            return False
