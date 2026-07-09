"""Parse JSON from LLM vision/game responses — strict, repair, then field fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("maya-unified.game.llm_json")


def extract_brace_block(raw: str) -> str | None:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(text[start:], start=start):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def repair_truncated_json(text: str) -> str:
    """Close strings/brackets when the model stopped mid-JSON."""
    blob = (text or "").strip()
    if not blob.startswith("{"):
        idx = blob.find("{")
        blob = blob[idx:] if idx >= 0 else blob

    in_str = False
    escape = False
    stack: list[str] = []
    for ch in blob:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()

    out = blob.rstrip()
    if in_str:
        out += '"'
    elif out.endswith(":"):
        out += ' ""'
    elif out.endswith(","):
        out = out[:-1]
    for opener in reversed(stack):
        out += "]" if opener == "[" else "}"
    return out


def _repair_with_library(blob: str) -> dict[str, Any] | None:
    try:
        import json_repair
    except ImportError:
        return None
    try:
        repaired = json_repair.repair_json(blob, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
        if isinstance(repaired, str):
            obj = json.loads(repaired)
            return obj if isinstance(obj, dict) else None
    except Exception as exc:  # noqa: BLE001
        log.debug("json_repair failed: %s", exc)
    return None


def _fallback_fields(blob: str, keys: tuple[str, ...]) -> dict[str, Any] | None:
    out: dict[str, Any] = {}
    for key in keys:
        match = re.search(
            rf'"{re.escape(key)}"\s*:\s*("(?:[^"\\]|\\.)*"|true|false|null|-?\d+(?:\.\d+)?)',
            blob,
            re.I | re.S,
        )
        if not match:
            match = re.search(rf"{re.escape(key)}\s*:\s*([A-Za-z_][\w]*)", blob, re.I)
        if not match:
            continue
        token = match.group(1).strip()
        if token.startswith('"'):
            try:
                out[key] = json.loads(token)
            except json.JSONDecodeError:
                out[key] = token.strip('"')
        elif token.lower() in ("true", "false"):
            out[key] = token.lower() == "true"
        elif token.lower() == "null":
            out[key] = None
        else:
            out[key] = token
    return out or None


def parse_llm_json_dict(
    raw: str,
    *,
    fallback_keys: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    """Best-effort JSON object parse: strict → truncate repair → json-repair → regex."""
    blob = extract_brace_block(raw)
    if not blob:
        return None

    for candidate in (blob, repair_truncated_json(blob)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue

    repaired = _repair_with_library(blob)
    if repaired:
        return repaired

    if fallback_keys:
        fields = _fallback_fields(blob, fallback_keys)
        if fields:
            return fields
    return None
