"""Thin async client for the direct Ideogram REST API.

Used as the primary path for the composite :class:`IdeogramProvider`; the fal
endpoint is the fallback. Sources the API key from the ``IDEOGRAM_API_KEY``
environment variable, falling back to OpenBao when available.

API shape follows the Ideogram 4.0 developer docs (developer.ideogram.ai):
base ``https://api.ideogram.ai``, ``Api-Key`` header, ``/generate/v4``,
``/remix/v4``, ``/generate/magic-prompt-v4``, and ``/describe/v4``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

IDEOGRAM_API_BASE = "https://api.ideogram.ai"
_OPENBAO_PATH = "secret/data/maya/providers/ideogram"


def resolve_api_key(explicit: Optional[str] = None) -> str:
    """Resolve the Ideogram API key: explicit > env > OpenBao."""
    if explicit:
        return explicit
    env_key = os.getenv("IDEOGRAM_API_KEY")
    if env_key:
        return env_key
    try:
        from lib.portal.openbao import _read_secret  # type: ignore

        secret = _read_secret(_OPENBAO_PATH) or {}
        value = secret.get("value") or secret.get("api_key") or ""
        if value:
            return value
    except Exception as exc:  # pragma: no cover - openbao optional
        logger.debug("ideogram_openbao_lookup_failed", error=str(exc))
    return ""


class IdeogramAPIError(Exception):
    """Raised when the direct Ideogram API call fails."""


class IdeogramAPIClient:
    """Async client wrapping the Ideogram 4.0 REST endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model: str = "V_4",
        base_url: str = IDEOGRAM_API_BASE,
        timeout: float = 120.0,
    ):
        self.api_key = resolve_api_key(api_key)
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        if not self.api_key:
            raise IdeogramAPIError("IDEOGRAM_API_KEY is not configured")
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Api-Key": self.api_key},
            timeout=self.timeout,
        )

    async def generate(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "ASPECT_1_1",
        magic_prompt_option: str = "AUTO",
        num_images: int = 1,
        seed: Optional[int] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "image_request": {
                "prompt": prompt,
                "model": self.model,
                "aspect_ratio": aspect_ratio,
                "magic_prompt_option": magic_prompt_option,
                "num_images": num_images,
            }
        }
        if seed is not None:
            payload["image_request"]["seed"] = seed
        async with self._client() as client:
            resp = await client.post("/generate/v4", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def remix(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        filename: str = "reference.png",
        image_weight: int = 50,
        aspect_ratio: str = "ASPECT_1_1",
    ) -> dict[str, Any]:
        image_request = {
            "prompt": prompt,
            "model": self.model,
            "image_weight": image_weight,
            "aspect_ratio": aspect_ratio,
        }
        async with self._client() as client:
            resp = await client.post(
                "/remix/v4",
                files={"image_file": (filename, image_bytes)},
                data={"image_request": json.dumps(image_request)},
            )
            resp.raise_for_status()
            return resp.json()

    async def magic_prompt(self, raw_prompt: str) -> str:
        """Expand a short prompt to Ideogram's structured JSON schema string."""
        async with self._client() as client:
            resp = await client.post(
                "/generate/magic-prompt-v4",
                json={"prompt": raw_prompt, "model": self.model},
            )
            resp.raise_for_status()
            return resp.json()["prompt"]

    async def describe(self, image_url: str) -> str:
        async with self._client() as client:
            resp = await client.post("/describe/v4", json={"image_url": image_url})
            resp.raise_for_status()
            descriptions = resp.json().get("descriptions") or []
            if not descriptions:
                return ""
            return descriptions[0].get("text", "")
