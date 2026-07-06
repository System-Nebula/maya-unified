"""Vision-based multi-critic image evaluation."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable

import structlog

from maya_image.director.state import CritiqueRecord, ImageGoal

logger = structlog.get_logger()

_CRITIC_PERSONAS: dict[str, str] = {
    "art": (
        "You are an art critic. Evaluate composition, lighting, color harmony, and visual balance. "
        "Return ONLY JSON: goal_match (0-1 float), issues (string array), objects (dict of bool)."
    ),
    "prompt": (
        "You are a prompt critic. Compare the image against the structured goal fields. "
        "Return ONLY JSON: goal_match (0-1 float), issues (string array), objects (dict of bool), "
        "missing_elements (string array)."
    ),
    "character": (
        "You are a character critic. Evaluate expression, personality, and emotional read. "
        "Return ONLY JSON: goal_match (0-1 float), issues (string array), objects (dict of bool)."
    ),
    "technical": (
        "You are a technical critic. Evaluate noise, anatomy, artifacts, and rendering quality. "
        "Return ONLY JSON: goal_match (0-1 float), issues (string array), objects (dict of bool)."
    ),
}

_MERGED_SYSTEM = (
    "You are an image critic for an autonomous artist agent. Given a structured goal and an image, "
    "return ONLY valid JSON with keys: goal_match (0-1 float), issues (string array), "
    "objects (dict string->bool), fixable_with_edit (bool), suggested_tool "
    "(image_edit_region|image_edit_style|image_generate|image_upscale), "
    "suggested_mask (string region name or empty), suggested_denoise (float 0-1)."
)


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _goal_summary(goal: ImageGoal) -> str:
    return json.dumps(goal.model_dump(exclude_none=True), indent=2)


def _build_vision_messages(
    *,
    system: str,
    goal: ImageGoal,
    image_part: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    user_text = f"Structured goal:\n{_goal_summary(goal)}\n\nEvaluate the image."
    if image_part:
        content: str | list[dict[str, Any]] = [
            {"type": "text", "text": user_text},
            image_part,
        ]
    else:
        content = user_text + "\n(No image available — estimate from goal only.)"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


async def _run_single_critic(
    *,
    critic_name: str,
    system: str,
    goal: ImageGoal,
    image_part: dict[str, Any] | None,
    llm: Any,
    vision_model: str,
) -> CritiqueRecord:
    messages = _build_vision_messages(system=system, goal=goal, image_part=image_part)
    try:
        resp = await asyncio.to_thread(
            llm.complete,
            messages,
            model=vision_model or None,
        )
        data = _extract_json(resp.content or "")
        return CritiqueRecord(
            critic=critic_name,
            goal_match=float(data.get("goal_match") or 0.5),
            issues=[str(i) for i in (data.get("issues") or []) if i],
            objects={str(k): bool(v) for k, v in (data.get("objects") or {}).items()},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("critic_failed", critic=critic_name, error=str(exc))
        return CritiqueRecord(critic=critic_name, goal_match=0.5, issues=[f"{critic_name} critic unavailable"])


def merge_critiques(critiques: list[CritiqueRecord]) -> CritiqueRecord:
    """Merge multiple critic passes into one actionable record."""
    if not critiques:
        return CritiqueRecord(critic="merged", goal_match=0.0)
    if len(critiques) == 1:
        c = critiques[0]
        return CritiqueRecord(
            critic="merged",
            goal_match=c.goal_match,
            issues=list(c.issues),
            objects=dict(c.objects),
            fixable_with_edit=c.fixable_with_edit,
            suggested_tool=c.suggested_tool,
            suggested_mask=c.suggested_mask,
            suggested_denoise=c.suggested_denoise,
        )

    scores = [c.goal_match for c in critiques if c.goal_match is not None]
    avg_score = sum(scores) / len(scores) if scores else 0.5
    issues: list[str] = []
    seen: set[str] = set()
    objects: dict[str, bool] = {}
    for c in critiques:
        for issue in c.issues:
            key = issue.lower().strip()
            if key and key not in seen:
                seen.add(key)
                issues.append(issue)
        for k, v in c.objects.items():
            objects[k] = objects.get(k, False) or v

    fixable = any(c.fixable_with_edit for c in critiques)
    suggested_tool = next((c.suggested_tool for c in critiques if c.suggested_tool), None)
    suggested_mask = next((c.suggested_mask for c in critiques if c.suggested_mask), None)
    suggested_denoise = next((c.suggested_denoise for c in critiques if c.suggested_denoise is not None), None)

    if not suggested_tool and issues:
        fixable = True
        suggested_tool = "image_edit_region"
        suggested_mask = suggested_mask or _guess_mask_from_issues(issues)

    return CritiqueRecord(
        critic="merged",
        goal_match=round(avg_score, 3),
        issues=issues,
        objects=objects,
        fixable_with_edit=fixable,
        suggested_tool=suggested_tool,
        suggested_mask=suggested_mask,
        suggested_denoise=suggested_denoise or 0.38,
    )


def _guess_mask_from_issues(issues: list[str]) -> str:
    joined = " ".join(issues).lower()
    if "hat" in joined:
        return "hat"
    if "background" in joined:
        return "background"
    if "face" in joined or "expression" in joined:
        return "face"
    return "subject"


async def score_image(
    *,
    goal: ImageGoal,
    image_url: str,
    llm: Any,
    vision_model: str = "",
    multi_critic: bool = True,
    emit: Callable[..., None] | None = None,
) -> CritiqueRecord:
    """Run vision critique on an image against structured goal."""
    image_part = None
    try:
        from services.imagine.remark import load_image_for_llm

        image_part = load_image_for_llm(image_url)
    except Exception as exc:  # noqa: BLE001
        logger.debug("critique_image_load_failed", error=str(exc))

    if not multi_critic:
        messages = _build_vision_messages(
            system=_MERGED_SYSTEM,
            goal=goal,
            image_part=image_part,
        )
        try:
            resp = await asyncio.to_thread(llm.complete, messages, model=vision_model or None)
            data = _extract_json(resp.content or "")
            return CritiqueRecord(
                critic="merged",
                goal_match=float(data.get("goal_match") or 0.5),
                issues=[str(i) for i in (data.get("issues") or []) if i],
                objects={str(k): bool(v) for k, v in (data.get("objects") or {}).items()},
                fixable_with_edit=bool(data.get("fixable_with_edit", True)),
                suggested_tool=str(data.get("suggested_tool") or "image_edit_region"),
                suggested_mask=str(data.get("suggested_mask") or "") or None,
                suggested_denoise=float(data.get("suggested_denoise") or 0.38),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("critique_merged_failed", error=str(exc))
            return CritiqueRecord(critic="merged", goal_match=0.5, issues=["critique unavailable"])

    tasks = [
        _run_single_critic(
            critic_name=name,
            system=prompt,
            goal=goal,
            image_part=image_part,
            llm=llm,
            vision_model=vision_model,
        )
        for name, prompt in _CRITIC_PERSONAS.items()
    ]
    results = await asyncio.gather(*tasks)
    merged = merge_critiques(list(results))

    if emit:
        try:
            emit(type="image.director.score", score=merged.goal_match, issues=merged.issues[:5])
        except Exception:  # noqa: BLE001
            pass

    return merged
