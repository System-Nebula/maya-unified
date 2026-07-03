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
    root = Path(CONFIG.data_dir)
    if not root.is_absolute():
        root = Path(os.path.dirname(os.path.abspath(__file__))).parents[2] / root
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
    # Fuzzy: match stem ignoring case
    stem = os.path.splitext(base)[0].lower()
    for fname in os.listdir(anim_dir):
        if os.path.splitext(fname)[0].lower() == stem:
            return fname
    return None


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
            "spoken": f"Playing {label}.",
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
                "Use the filename or friendly name from list_avatar_animations. "
                "One-shot clips return to idle automatically; set loop=true only for sustained poses."
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
