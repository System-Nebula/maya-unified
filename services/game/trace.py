"""Structured game pipeline traces — JSONL per operator for debugging."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("maya-unified.game.trace")

_ROOT = Path(__file__).resolve().parents[2]
_TRACE_DIR = _ROOT / "data" / "game_traces"
_lock = threading.Lock()


def _trace_path(operator_id: str) -> Path:
    return _TRACE_DIR / f"{operator_id}.jsonl"


def game_trace(
    operator_id: str,
    event: str,
    *,
    level: str = "info",
    **fields: Any,
) -> None:
    """Append one JSON line to the operator trace log."""
    oid = str(operator_id or "unknown")
    row: dict[str, Any] = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "event": event,
        "level": level,
        **fields,
    }
    try:
        _TRACE_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, default=str) + "\n"
        with _lock:
            with _trace_path(oid).open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception as exc:  # noqa: BLE001
        log.debug("trace write failed: %s", exc)

    msg = f"trace {event}"
    if fields:
        brief = {k: fields[k] for k in list(fields)[:6]}
        msg = f"{msg} {brief}"
    if level == "error":
        log.error(msg)
    elif level == "warning":
        log.warning(msg)
    else:
        log.info(msg)


def read_trace_tail(operator_id: str, *, max_lines: int = 40) -> list[dict[str, Any]]:
    path = _trace_path(str(operator_id))
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-max_lines:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except Exception:  # noqa: BLE001
        return []
