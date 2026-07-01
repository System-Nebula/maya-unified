"""fal provider for Hunyuan Image 3.0 Instruct edit/generate."""

from __future__ import annotations

from maya_image.providers.fal_base import FalBaseImageProvider
from maya_image.types.image_job import ImageJobInput


class FalHunyuanImage3Provider(FalBaseImageProvider):
    _GENERATE_ENDPOINT = "fal-ai/hunyuan-image-3-instruct-gpu"
    _EDIT_ENDPOINT = "fal-ai/hunyuan-image-3-instruct-gpu/edit"

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
            "guidance_scale": 3.5,
            "enable_prompt_expansion": True,
            "enable_safety_checker": True,
            "output_format": "png",
        }
        if request.references:
            payload["image_urls"] = [ref.source_url for ref in request.references]
        return payload
