"""fal provider for Qwen Image Edit Plus 2511 edit/generate."""

from __future__ import annotations

from maya_image.providers.fal_base import FalBaseImageProvider
from maya_image.types.image_job import ImageJobInput


class FalQwenImageEditPlusProvider(FalBaseImageProvider):
    _GENERATE_ENDPOINT = "fal-ai/qwen-image-edit-plus"
    _EDIT_ENDPOINT = "fal-ai/qwen-image-edit-plus/edit"

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
            "image_size": self._size_to_image_size(request.size),
            "num_images": 1,
            "output_format": "png",
        }
        if request.references:
            payload["image_urls"] = [ref.source_url for ref in request.references]
        return payload
