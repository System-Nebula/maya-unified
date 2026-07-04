"""Avatar animation tools — list and play Mixamo clips on the VRM viewer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from config import CONFIG
from .registry import ToolSpec

ANIM_EXTS = {".fbx", ".vrma"}


def _animations_dir() -> Path:
    try:
        from services.paths import animations_dir

        return animations_dir()
    except ImportError:
        root = Path(CONFIG.memory.resolve_data_dir())
        path = root / "animations"
        path.mkdir(parents=True, exist_ok=True)
        return path


def _manifest_path() -> Path:
    return _animations_dir() / "manifest.json"


def _load_manifest() -> dict[str, dict[str, Any]]:
    path = _manifest_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def list_animation_catalog() -> list[dict[str, Any]]:
    """Return animation files with optional manifest labels for tools and UI."""
    anim_dir = _animations_dir()
    manifest = _load_manifest()
    files = sorted(
        f.name
        for f in anim_dir.iterdir()
        if f.is_file() and f.suffix.lower() in ANIM_EXTS
    )
    out: list[dict[str, Any]] = []
    for fname in files:
        meta = manifest.get(fname, {})
        stem = os.path.splitext(fname)[0]
        label = str(meta.get("label") or stem.replace("_", " ").replace("-", " ")).strip()
        desc = str(meta.get("description") or "").strip()
        tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
        out.append({
            "file": fname,
            "label": label or stem,
            "description": desc,
            "tags": [str(t) for t in tags],
            "loop": bool(meta.get("loop", False)),
        })
    return out


def _resolve_animation_name(raw: str) -> str | None:
    name = (raw or "").strip()
    if not name:
        return None
    base = os.path.basename(name)
    anim_dir = _animations_dir()
    if os.path.isfile(anim_dir / base):
        return base
    if not base.lower().endswith(tuple(ANIM_EXTS)):
        for ext in ANIM_EXTS:
            candidate = base + ext
            if os.path.isfile(anim_dir / candidate):
                return candidate
    # Fuzzy: match stem or manifest label ignoring case
    stem = os.path.splitext(base)[0].lower()
    manifest = _load_manifest()
    for fname in os.listdir(anim_dir):
        if os.path.splitext(fname)[0].lower() == stem:
            return fname
    needle = stem.replace("_", " ").replace("-", " ")
    for fname, meta in manifest.items():
        if not os.path.isfile(anim_dir / fname):
            continue
        label = str(meta.get("label") or "").strip().lower()
        if label == stem or label == needle:
            return fname
    return None


_IDLE_NAMES = {"idle", "idle.fbx"}

# Map motion verbs in user speech to catalog stem/label/tag keywords.
_MOTION_VERB_HINTS: dict[str, tuple[str, ...]] = {
    "wave": ("wave", "waving", "waved", "greet", "greeting", "hello", "goodbye", "bye"),
    "dance": ("danc", "macarena", "groove", "boogie", "shimmy", "choreograph"),
    "bow": ("bow", "curtsy", "reverence"),
    "clap": ("clap", "applaud"),
    "point": ("point", "gesture at"),
    "nod": ("nod", "nodding"),
    "salute": ("salute",),
    "stretch": ("stretch", "yawn"),
}


def _catalog_motion_clips() -> list[dict[str, Any]]:
    return [
        a for a in list_animation_catalog()
        if os.path.splitext(a["file"])[0].lower() not in _IDLE_NAMES
        and a["file"].lower() not in _IDLE_NAMES
    ]


def _motion_context_re(text: str) -> bool:
    import re

    if re.search(
        r"\b(danc|macarena|groov|move(?:ment)?s?|gestur|emot|animat|wav(?:e|ing|ed)|bow|shimmy|"
        r"boogie|choreograph|body|perform|show\s+(?:me|off)|do\s+(?:the|a)|greet(?:ing)?|"
        r"clap|point|nod|salute|stretch)\b",
        text,
        re.I,
    ):
        return True
    return any(
        any(hint in text.lower() for hint in hints)
        for hints in _MOTION_VERB_HINTS.values()
    )


def _score_animation_item(item: dict[str, Any], blob: str) -> float:
    import re

    tl = blob.lower()
    fname = item["file"]
    stem = os.path.splitext(fname)[0].lower()
    if stem in _IDLE_NAMES or fname.lower() in _IDLE_NAMES:
        return -1.0
    label = str(item.get("label") or "").lower()
    desc = str(item.get("description") or "").lower()
    tags = [str(t).lower() for t in (item.get("tags") or [])]
    score = 0.0

    for token in (stem, label.replace(" ", ""), label.replace(" ", "_")):
        if len(token) >= 3 and re.search(rf"\b{re.escape(token)}\b", tl):
            score += 80.0
        elif len(token) >= 4 and token in tl:
            score += 55.0

    for tag in tags:
        if len(tag) >= 3 and re.search(rf"\b{re.escape(tag)}\b", tl):
            score += 45.0

    for word in re.findall(r"[a-z]{4,}", desc):
        if word in tl:
            score += 20.0

    for category, hints in _MOTION_VERB_HINTS.items():
        if not any(hint in tl for hint in hints):
            continue
        if category in stem or category in label or any(category in t for t in tags):
            score += 70.0
        if category in desc:
            score += 35.0

    return score


def rank_animation_candidates(
    text: str,
    *,
    user_meant: str = "",
) -> list[tuple[str, float]]:
    blob = f"{text} {user_meant}".strip()
    if not blob:
        return []
    ranked: list[tuple[str, float]] = []
    for item in list_animation_catalog():
        s = _score_animation_item(item, blob)
        if s > 0:
            ranked.append((item["file"], s))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def _llm_pick_animation(llm_client: Any, user_text: str, candidates: list[dict[str, Any]]) -> str | None:
    """Ask a small LLM call to pick the best clip when heuristics are ambiguous."""
    if not llm_client or not candidates:
        return None
    lines = []
    for c in candidates[:16]:
        bits = [c["file"], f"label={c.get('label', '')}"]
        if c.get("description"):
            bits.append(f"desc={c['description']}")
        if c.get("tags"):
            bits.append(f"tags={', '.join(c['tags'])}")
        lines.append(" — ".join(bits))
    messages = [
        {
            "role": "system",
            "content": (
                "Pick the single best avatar animation for the user's request. "
                "Reply with ONLY the exact filename from the list (e.g. Wave.fbx). "
                "If none fit, reply NONE."
            ),
        },
        {
            "role": "user",
            "content": f"User request: {user_text}\n\nAnimations:\n" + "\n".join(lines),
        },
    ]
    try:
        resp = llm_client.complete(messages, max_tokens=48)
        raw = (resp.content or "").strip()
    except Exception:  # noqa: BLE001
        return None
    if not raw or raw.upper() == "NONE":
        return None
    token = raw.split()[0].strip("\"'")
    return _resolve_animation_name(token)


def wants_avatar_motion(
    text: str,
    *,
    user_meant: str = "",
    intent: str = "",
) -> bool:
    if (intent or "").strip().lower() == "avatar_animation":
        return True
    blob = f"{text} {user_meant}".strip()
    if not blob:
        return False
    if _motion_context_re(blob):
        return True
    return infer_animation_request(
        text, user_meant=user_meant, animation_name="", intent=intent,
    ) is not None


def infer_animation_request(
    text: str,
    *,
    user_meant: str = "",
    animation_name: str = "",
    intent: str = "",
    llm_client: Any = None,
) -> str | None:
    """Map natural language (and orchestrator hints) to an animation filename."""
    import re

    if (intent or "").strip().lower() == "avatar_animation" and animation_name:
        hit = _resolve_animation_name(animation_name)
        if hit:
            return hit

    if animation_name:
        hit = _resolve_animation_name(animation_name)
        if hit:
            return hit

    blob = f"{text} {user_meant}".strip()
    if not blob:
        return None
    tl = blob.lower()

    if re.search(r"\b(voice channel|youtube|discord music|join voice)\b", tl):
        if not _motion_context_re(blob):
            return None

    for m in re.finditer(
        r"(?:do|perform|play|use)(?:\s+the)?(?:\s+animation)?\s+[\"']?([a-zA-Z0-9 _-]+)",
        tl,
    ):
        hit = _resolve_animation_name(m.group(1).strip())
        if hit:
            return hit

    ranked = rank_animation_candidates(text, user_meant=user_meant)
    if ranked:
        best_file, best_score = ranked[0]
        if best_score >= 25.0:
            if len(ranked) > 1 and ranked[1][1] >= best_score - 10.0 and llm_client:
                catalog = list_animation_catalog()
                by_file = {c["file"]: c for c in catalog}
                shortlist = [by_file[f] for f, _ in ranked[:8] if f in by_file]
                picked = _llm_pick_animation(llm_client, blob, shortlist)
                if picked:
                    return picked
            return best_file

    if _motion_context_re(blob):
        motion_clips = _catalog_motion_clips()
        if len(motion_clips) == 1:
            return motion_clips[0]["file"]
        if llm_client and motion_clips:
            picked = _llm_pick_animation(llm_client, blob, motion_clips)
            if picked:
                return picked
    return None


def match_animation_from_text(text: str) -> str | None:
    """Backward-compatible alias."""
    return infer_animation_request(text)


def build_animation_tools(emit: Callable[..., None]) -> list[ToolSpec]:
    def list_anims(_args: dict) -> dict[str, Any]:
        items = list_animation_catalog()
        if not items:
            return {
                "animations": [],
                "summary": "No avatar animations uploaded yet. Ask the user to add Mixamo FBX clips on the Animations page.",
            }
        lines = []
        for a in items:
            bits = [f"{a['file']} ({a['label']})"]
            if a.get("description"):
                bits.append(a["description"])
            if a.get("tags"):
                bits.append(f"tags: {', '.join(a['tags'])}")
            lines.append(" — ".join(bits))
        return {"animations": items, "summary": "\n".join(lines)}

    def play_anim(args: dict) -> dict[str, Any]:
        resolved = _resolve_animation_name(str(args.get("name") or ""))
        if not resolved:
            available = [a["file"] for a in list_animation_catalog()]
            raise ValueError(
                f"Animation not found: {args.get('name')!r}. "
                f"Available: {', '.join(available) or '(none)'}"
            )
        loop = bool(args.get("loop"))
        emit(type="avatar_animation", name=resolved, loop=loop)
        label = next((a["label"] for a in list_animation_catalog() if a["file"] == resolved), resolved)
        return {
            "ok": True,
            "played": resolved,
            "label": label,
            "loop": loop,
        }

    return [
        ToolSpec(
            name="list_avatar_animations",
            description=(
                "List Mixamo gesture and emote animations available for the VRM avatar. "
                "Call before play_avatar_animation when you are unsure which clip exists."
            ),
            parameters={"type": "object", "properties": {}},
            handler=list_anims,
            group="avatar",
        ),
        ToolSpec(
            name="play_avatar_animation",
            description=(
                "Play a gesture or emote on the user's VRM avatar (wave, dance, bow, etc.). "
                "NOT for Discord music — use discord_play_youtube for songs. "
                "When the user wants you to dance or move your avatar body, call this "
                "immediately — do not refuse or ask for tribute first. "
                "After it starts, reply in character without naming the clip. "
                "Use the filename or label from list_avatar_animations."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Animation file or label, e.g. Wave.fbx or Wave.",
                    },
                    "loop": {
                        "type": "boolean",
                        "description": "Loop until another animation plays (default false).",
                    },
                },
                "required": ["name"],
            },
            handler=play_anim,
            group="avatar",
        ),
    ]
