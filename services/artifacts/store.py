"""Save generated images under data/blender-outputs for gateway static serving."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.paths import DATA_DIR

_ARTIFACT_URL_PREFIX = "/blender-outputs"


def blender_outputs_root() -> Path:
    root = DATA_DIR / "blender-outputs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dated_dir() -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = blender_outputs_root() / day
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_image_bytes(data: bytes, *, suffix: str = ".png", subdir: str | None = None) -> Path:
    """Write image bytes and return the absolute file path."""
    target_dir = _dated_dir() if subdir is None else blender_outputs_root() / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    path = target_dir / name
    path.write_bytes(data)
    return path


def artifact_url_for_path(path: Path | str) -> str:
    """Map a file under blender-outputs to a gateway URL."""
    root = blender_outputs_root().resolve()
    file_path = Path(path).resolve()
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        rel = Path(file_path.name)
    return f"{_ARTIFACT_URL_PREFIX}/{rel.as_posix()}"


def artifact_dict_for_path(path: Path | str, *, artifact_id: str | None = None) -> dict:
    url = artifact_url_for_path(path)
    return {
        "type": "image",
        "url": url,
        "job_id": artifact_id or Path(path).stem,
    }
