"""Build Ideogram 4.0 structured-JSON captions from free-text user input.

Two paths:

* **Path A (``api``)** — call Ideogram's magic-prompt endpoint via
  :class:`IdeogramAPIClient`. Best for the Discord UX where users type naturally.
* **Path B (``local``)** — build the structured caption with an internal LLM call
  (``lib.llm.complete_json``). Useful when offline / cost-sensitive, or when the
  direct API is unavailable.

Ideogram 4 is trained on structured JSON captions. The schema
(github.com/ideogram-oss/ideogram4/docs/prompting.md) is:

```json
{
  "high_level_description": "A one- or two-sentence summary of the whole image.",
  "style_description": {
    "aesthetics": "moody, cinematic, desaturated",
    "lighting": "golden hour, rim light",
    "photo": "wide angle, f/8, long exposure",
    "medium": "photograph",
    "color_palette": ["#FF6B35", "#004E89"]
  },
  "compositional_deconstruction": {
    "background": "Description of the environment.",
    "elements": [
      {"type": "obj", "bbox": [400, 350, 700, 650], "desc": "A subject.",
       "color_palette": ["#FFFFFF"]},
      {"type": "text", "bbox": [100, 200, 180, 800], "text": "ACME",
       "desc": "Bold company name."}
    ]
  }
}
```

Key rules (quality-critical):
* ``style_description`` is an object. When present it needs ``aesthetics``,
  ``lighting``, ``medium`` and exactly one of ``photo`` (photographs) or
  ``art_style`` (everything else); ``color_palette`` is optional.
* ``compositional_deconstruction`` is required: ``background`` (string) then
  ``elements`` (list). ``obj`` elements use ``desc``; ``text`` elements add ``text``.
* ``bbox`` is ``[y_min, x_min, y_max, x_max]`` in **integer 0–1000** coordinates.
* ``color_palette`` is **uppercase** ``#RRGGBB`` (≤16 at style level, ≤5 per element).
* **Key order is strict and affects generation quality** — we reorder on the Python
  side rather than trusting the LLM. Serialize compact (no spaces).
* There is **no negative prompt** — Ideogram uses asymmetric CFG.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog

from maya_image.providers.ideogram_api import IdeogramAPIClient

logger = structlog.get_logger()

MEDIUM_VALUES = ("photograph", "illustration", "3d_render", "painting", "graphic_design")
ELEMENT_TYPES = ("obj", "text")

# Canonical key orders (see schema rules above).
_STYLE_ORDER_PHOTO = ("aesthetics", "lighting", "photo", "medium", "color_palette")
_STYLE_ORDER_ART = ("aesthetics", "lighting", "medium", "art_style", "color_palette")
_ELEMENT_ORDER_OBJ = ("type", "bbox", "desc", "color_palette")
_ELEMENT_ORDER_TEXT = ("type", "bbox", "text", "desc", "color_palette")
_TOP_ORDER = ("high_level_description", "style_description", "compositional_deconstruction")

_SCHEMA_SYSTEM_PROMPT = """\
You convert a short image request into an Ideogram 4.0 structured JSON caption.
Return ONLY a JSON object (no markdown fences) with these keys in this order:

1. "high_level_description": a one- or two-sentence summary of the whole image.
2. "style_description": an object with, in order:
   - "aesthetics": aesthetic keywords (e.g. "moody, cinematic, desaturated")
   - "lighting": lighting description (e.g. "golden hour, rim light")
   - for a PHOTOGRAPH add "photo" (camera/lens, e.g. "wide angle, f/8") BEFORE "medium";
     otherwise add "art_style" (e.g. "flat vector design") AFTER "medium"
   - "medium": one of photograph | illustration | 3d_render | painting | graphic_design
   - "color_palette" (optional): up to 16 UPPERCASE hex colors like "#FF6B35"
3. "compositional_deconstruction": an object with, in order:
   - "background": description of the environment (string)
   - "elements": a list of objects. Each is either
       {"type":"obj","bbox":[y_min,x_min,y_max,x_max],"desc":"...","color_palette":["#FFFFFF"]}
     or for in-image text
       {"type":"text","bbox":[...],"text":"LITERAL TEXT","desc":"...","color_palette":[...]}
     bbox is OPTIONAL and uses INTEGER coordinates 0..1000 as [y_min, x_min, y_max, x_max].
     Per-element color_palette holds up to 5 UPPERCASE hex colors.

Do NOT include a negative prompt. Do NOT add keys beyond those listed.

Example:
{"high_level_description":"A lone sailboat on calm water at sunset.","style_description":\
{"aesthetics":"serene, warm, golden hour","lighting":"golden hour backlighting, warm haze",\
"photo":"wide angle, f/8, long exposure","medium":"photograph",\
"color_palette":["#FF6B35","#F7C59F","#004E89"]},"compositional_deconstruction":\
{"background":"A calm ocean to a low horizon, sky washed orange and pink.",\
"elements":[{"type":"obj","desc":"A single sailboat with a white triangular sail, \
silhouetted against the setting sun."}]}}"""


def order_caption(raw: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a caption dict in Ideogram's canonical, quality-critical key order.

    Drops ``None``/empty values and unknown keys. Branches ``style_description`` on
    photo-vs-art_style and each element on ``type``.
    """

    def _ordered(source: dict, keys: tuple[str, ...]) -> dict:
        out: dict[str, Any] = {}
        for key in keys:
            value = source.get(key)
            if value is None or value == "" or value == [] or value == {}:
                continue
            out[key] = value
        return out

    result: dict[str, Any] = {}

    if raw.get("high_level_description"):
        result["high_level_description"] = raw["high_level_description"]

    style = raw.get("style_description")
    if isinstance(style, dict) and style:
        order = _STYLE_ORDER_PHOTO if style.get("photo") else _STYLE_ORDER_ART
        ordered_style = _ordered(style, order)
        if ordered_style:
            result["style_description"] = ordered_style

    comp = raw.get("compositional_deconstruction")
    if isinstance(comp, dict) and comp:
        ordered_comp: dict[str, Any] = {}
        if comp.get("background"):
            ordered_comp["background"] = comp["background"]
        elements = []
        for el in comp.get("elements") or []:
            if not isinstance(el, dict):
                continue
            keys = _ELEMENT_ORDER_TEXT if el.get("type") == "text" else _ELEMENT_ORDER_OBJ
            ordered_el = _ordered(el, keys)
            if ordered_el:
                elements.append(ordered_el)
        if elements:
            ordered_comp["elements"] = elements
        if ordered_comp:
            result["compositional_deconstruction"] = ordered_comp

    return result


def serialize_caption(raw: dict[str, Any]) -> str:
    """Canonical-order, compact JSON serialization per the Ideogram guide."""
    return json.dumps(order_caption(raw), separators=(",", ":"), ensure_ascii=False)


class IdeogramPromptBuilder:
    """Expand free-text into Ideogram 4.0 structured-JSON caption strings."""

    def __init__(self, *, api_client: Optional[IdeogramAPIClient] = None, llm_config=None):
        self._api_client = api_client
        self._llm_config = llm_config

    async def build(self, raw_prompt: str, *, path: str = "api") -> str:
        """Return a structured-JSON caption string for ``raw_prompt``.

        ``path`` is ``"api"`` (magic prompt endpoint) or ``"local"`` (LLM).
        """
        if path == "api":
            return await self._build_api(raw_prompt)
        if path == "local":
            return await self._build_local(raw_prompt)
        raise ValueError(f"unknown prompt builder path: {path}")

    async def _build_api(self, raw_prompt: str) -> str:
        client = self._api_client or IdeogramAPIClient()
        return await client.magic_prompt(raw_prompt)

    async def _build_local(self, raw_prompt: str) -> str:
        from lib.llm import complete_json

        messages = [
            {"role": "system", "content": _SCHEMA_SYSTEM_PROMPT},
            {"role": "user", "content": raw_prompt},
        ]
        obj = await complete_json(messages, config=self._llm_config)
        if not isinstance(obj, dict):
            raise ValueError("LLM did not return a JSON object caption")
        return serialize_caption(obj)
