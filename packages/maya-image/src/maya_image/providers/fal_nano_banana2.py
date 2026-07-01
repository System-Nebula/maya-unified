"""fal provider for Nano Banana 2 edit/generate."""

from __future__ import annotations

from maya_image.providers.fal_base import FalBaseImageProvider
from maya_image.types.image_job import ImageJobInput, ImageMode


class FalNanoBanana2Provider(FalBaseImageProvider):
    _GENERATE_ENDPOINT = "fal-ai/nano-banana-2"
    _EDIT_ENDPOINT = "fal-ai/nano-banana-2/edit"

    @property
    def endpoint_id(self) -> str:
        return self._GENERATE_ENDPOINT

    @property
    def model_key(self) -> str:
        return self._EDIT_ENDPOINT

    def _resolve_endpoint(self, request: ImageJobInput) -> str:
        if request.references:
            return self._EDIT_ENDPOINT
        return self._GENERATE_ENDPOINT

    def build_payload(self, request: ImageJobInput) -> dict[str, object]:
        payload: dict[str, object] = {
            "prompt": request.prompt,
            "aspect_ratio": self._size_to_aspect_ratio(request.size),
            "resolution": self._size_to_resolution(request.size),
        }
        if request.references:
            payload["image_urls"] = [ref.source_url for ref in request.references]
        return payload
