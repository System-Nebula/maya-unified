"""fal provider for Ideogram, used as the fallback path for IdeogramProvider.

NOTE: the exact fal endpoint slug should be verified against fal's catalogue.
Ideogram 4 may not yet be on fal at the time of writing; the v3 endpoint serves
as the fallback until v4 lands. Update ``_GENERATE_ENDPOINT`` / ``_EDIT_ENDPOINT``
when the v4 slug is confirmed.
"""

from __future__ import annotations

from maya_image.providers.fal_base import FalBaseImageProvider
from maya_image.types.image_job import ImageJobInput


class FalIdeogramProvider(FalBaseImageProvider):
    _GENERATE_ENDPOINT = "fal-ai/ideogram/v3"
    _EDIT_ENDPOINT = "fal-ai/ideogram/v3/remix"

    @property
    def endpoint_id(self) -> str:
        return self._GENERATE_ENDPOINT

    @property
    def model_key(self) -> str:
        return self._GENERATE_ENDPOINT

    def _resolve_endpoint(self, request: ImageJobInput) -> str:
        if request.references:
            return self._EDIT_ENDPOINT
        return self._GENERATE_ENDPOINT

    def build_payload(self, request: ImageJobInput) -> dict[str, object]:
        payload: dict[str, object] = {
            "prompt": request.prompt,
            "aspect_ratio": self._size_to_aspect_ratio(request.size),
            "num_images": 1,
        }
        if request.references:
            payload["image_urls"] = [ref.source_url for ref in request.references]
        return payload
