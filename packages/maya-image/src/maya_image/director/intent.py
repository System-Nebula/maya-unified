"""Parse user intent into structured ImageGoal deltas."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from maya_image.director.state import ImageSessionState

logger = structlog.get_logger()

_INTENT_SYSTEM = (
    "You are an image intent parser. Given the current structured image goal and a user "
    "message, return ONLY valid JSON with keys: "
    "state_delta (nested object matching goal fields to change), "
    "rationale (short string), "
    "suggested_next_tool (one of: image_generate, image_edit_region, image_edit_style, "
    "image_upscale, image_restore_version, image_score), "
    "suggested_params (object with optional mask, denoise, version_id). "
    "Never return a raw prompt string. Mutate structured goal fields only."
)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _heuristic_parse(message: str, state: ImageSessionState) -> dict[str, Any]:
    """Rule-based fallback when LLM is unavailable."""
    msg = message.lower().strip()
    delta: dict[str, Any] = {}
    tool = "image_generate"
    params: dict[str, Any] = {}

    if any(w in msg for w in ("bigger", "larger", " enlarge")):
        tool = "image_edit_region"
        params = {"mask": "subject", "denoise": 0.38}
    elif any(w in msg for w in ("background", "backdrop", "scene")):
        if state.current_image_url:
            tool = "image_edit_region"
            params = {"mask": "background", "denoise": 0.55}
        else:
            delta["background"] = message.strip()
    elif any(w in msg for w in ("sad", "happy", "angry", "stupid", "expression")):
        delta["expression"] = message.strip()
        tool = "image_edit_style" if state.current_image_url else "image_generate"
        params = {"denoise": 0.45}
    elif "hat" in msg or "runescape" in msg or "party hat" in msg:
        hat: dict[str, Any] = {}
        if "blue" in msg:
            hat["color"] = "blue"
        if "runescape" in msg:
            hat["type"] = "runescape_blue_party_hat"
        elif "party" in msg:
            hat["type"] = "party_hat"
        if hat:
            delta["hat"] = hat
        tool = "image_edit_region" if state.current_image_url else "image_generate"
        params = {"mask": "hat", "denoise": 0.38}
    elif any(w in msg for w in ("draw", "generate", "create", "make", "picture", "image")):
        delta["subject"] = message.strip()
        tool = "image_generate"
    else:
        delta["extras"] = {"note": message.strip()}
        tool = "image_edit_region" if state.current_image_url else "image_generate"

    return {
        "state_delta": delta,
        "rationale": "heuristic parse",
        "suggested_next_tool": tool,
        "suggested_params": params,
    }


async def parse_intent(
    message: str,
    state: ImageSessionState,
    *,
    llm: Any | None = None,
) -> dict[str, Any]:
    """Parse user message into a state delta and planner hints."""
    message = (message or "").strip()
    if not message:
        return {
            "state_delta": {},
            "rationale": "empty message",
            "suggested_next_tool": "image_get_state",
            "suggested_params": {},
        }

    if llm is None:
        return _heuristic_parse(message, state)

    user_payload = json.dumps(
        {
            "current_goal": state.goal.model_dump(),
            "has_image": bool(state.current_image_url),
            "user_message": message,
        },
        indent=2,
    )
    messages = [
        {"role": "system", "content": _INTENT_SYSTEM},
        {"role": "user", "content": user_payload},
    ]
    try:
        resp = llm.complete(messages)
        parsed = _extract_json(resp.content or "")
        if parsed and isinstance(parsed.get("state_delta"), dict):
            return {
                "state_delta": parsed.get("state_delta") or {},
                "rationale": str(parsed.get("rationale") or ""),
                "suggested_next_tool": str(parsed.get("suggested_next_tool") or "image_generate"),
                "suggested_params": parsed.get("suggested_params") or {},
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("intent_llm_failed", error=str(exc))

    return _heuristic_parse(message, state)
