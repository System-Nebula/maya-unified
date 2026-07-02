"""Per-operator Google refresh token storage (file-based dev fallback)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from services.integrations.google.config import MAYA_GOOGLE_TOKEN_DIR


def _token_path(operator_id: uuid.UUID | str) -> Path:
    base = Path(MAYA_GOOGLE_TOKEN_DIR)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{operator_id}.json"


def read_tokens(operator_id: uuid.UUID | str) -> dict[str, Any] | None:
    path = _token_path(operator_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_tokens(operator_id: uuid.UUID | str, data: dict[str, Any]) -> None:
    path = _token_path(operator_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def delete_tokens(operator_id: uuid.UUID | str) -> None:
    path = _token_path(operator_id)
    if path.is_file():
        path.unlink()
