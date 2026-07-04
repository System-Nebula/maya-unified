"""Parse tool calls the model wrote as plain text instead of structured API calls.

Models without reliable native tool calling (Gemma, some local chat models, etc.)
often leak syntax like call:tool{...}, <tool_call>...</tool_call>, or JSON blobs.
This module normalizes those variants before execution or display stripping.
"""

from __future__ import annotations

import json
import re
from typing import Any

# call:tool_name{key:"value"} — with or without <|tool_call|> wrappers
_WRAPPED_CALL_RE = re.compile(
    r"<\|?\s*tool_call\s*\|?>\s*call:(?P<name>[a-zA-Z0-9_]+)\s*\{(?P<args>[^}]*)\}\s*"
    r"<\|?\s*tool_call\s*\|?>",
    re.IGNORECASE,
)
_INLINE_CALL_RE = re.compile(
    r"call:(?P<name>[a-z][a-z0-9_]*)\s*\{(?P<args>[^}]+)\}",
    re.IGNORECASE,
)
# <function=discord_play_youtube>{"query":"..."}</function>
_FUNCTION_TAG_RE = re.compile(
    r"<function=(?P<name>[a-zA-Z0-9_]+)>\s*(?P<json>\{.*?\})\s*</function>",
    re.IGNORECASE | re.DOTALL,
)
# tool_name(key="value") or tool_name("single positional")
_PAREN_CALL_RE = re.compile(
    r"(?P<name>[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*\(\s*(?P<body>[^)]*)\s*\)",
    re.IGNORECASE,
)
_STRIP_WRAPPED_CALL_RE = re.compile(
    r"<\|?\s*tool_call\s*\|?>\s*call:[a-zA-Z0-9_]+\s*\{[^}]*\}\s*<\|?\s*tool_call\s*\|?>",
    re.IGNORECASE,
)
_STRIP_INLINE_CALL_RE = re.compile(
    r"call:[a-z][a-z0-9_]*\s*\{[^}]+\}",
    re.IGNORECASE,
)
_STRIP_FUNCTION_TAG_RE = re.compile(
    r"<function=[a-zA-Z0-9_]+>\s*\{.*?\}\s*</function>",
    re.IGNORECASE | re.DOTALL,
)
_STRIP_PAREN_CALL_RE = re.compile(
    r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+\s*\([^)]*\)",
    re.IGNORECASE,
)
_STRIP_TOOL_JSON_RE = re.compile(
    r"<\|?\s*tool_call\s*\|?>\s*\{[^}]*\}\s*<\|?\s*tool_call\s*\|?>",
    re.IGNORECASE | re.DOTALL,
)


def _iter_json_objects(text: str):
    """Yield (start, end, substring) for each top-level balanced {...} block."""
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
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
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield start, i + 1, text[start : i + 1]


def _normalize_token_value(raw: str) -> str:
    value = (raw or "").strip()
    value = re.sub(r"^<\|\"\|>", "", value)
    value = re.sub(r"<\|\"\|>$", "", value)
    return value.strip("\"' ")


def _parse_brace_args(args_str: str) -> dict[str, Any]:
    body = (args_str or "").strip()
    if not body:
        return {}
    body = body.replace("<|\"|>", '"')
    try:
        if body.startswith("{"):
            obj = json.loads(body)
            if isinstance(obj, dict):
                return obj
    except (TypeError, ValueError):
        pass
    out: dict[str, Any] = {}
    for match in re.finditer(r"(\w+)\s*:\s*\"([^\"]*)\"", body):
        out[match.group(1)] = match.group(2)
    if out:
        return out
    for match in re.finditer(r"(\w+)\s*:\s*'([^']*)'", body):
        out[match.group(1)] = match.group(2)
    if out:
        return out
    for match in re.finditer(r"(\w+)\s*:\s*([^,]+)", body):
        out[match.group(1)] = _normalize_token_value(match.group(2))
    return out


def _parse_paren_args(tool_name: str, body: str) -> dict[str, Any]:
    raw = (body or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except (TypeError, ValueError):
            pass
    m = re.match(r"^[\"'](.+)[\"']$", raw)
    if m:
        key = "query" if tool_name.startswith("discord_") else "name"
        return {key: m.group(1)}
    kw = dict(re.findall(r"(\w+)\s*=\s*[\"']([^\"']*)[\"']", raw))
    if kw:
        return kw
    kw = dict(re.findall(r"(\w+)\s*=\s*([^,)]+)", raw))
    if kw:
        return {k: _normalize_token_value(v) for k, v in kw.items()}
    return {}


def _normalize_json_tool(obj: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    name = obj.get("tool") or obj.get("name") or obj.get("function")
    if not isinstance(name, str) or not name.strip():
        return None
    args = obj.get("args") or obj.get("arguments") or obj.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (TypeError, ValueError):
            args = {"query": args} if name.startswith("discord_") else {}
    if not isinstance(args, dict):
        args = {}
    return name.strip(), args


def _add_call(
    calls: list[tuple[str, dict[str, Any]]],
    seen: set[tuple[str, str]],
    name: str,
    args: dict[str, Any],
) -> None:
    clean_name = (name or "").strip()
    if not clean_name or not isinstance(args, dict):
        return
    key = (clean_name, json.dumps(args, sort_keys=True))
    if key in seen:
        return
    seen.add(key)
    calls.append((clean_name, args))


def parse_text_tool_calls(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Return [(tool_name, args), ...] from any known leaked plain-text syntax."""
    if not text:
        return []
    seen: set[tuple[str, str]] = set()
    calls: list[tuple[str, dict[str, Any]]] = []

    for pattern in (_WRAPPED_CALL_RE, _INLINE_CALL_RE):
        for match in pattern.finditer(text):
            _add_call(
                calls,
                seen,
                match.group("name"),
                _parse_brace_args(match.group("args")),
            )

    for match in _FUNCTION_TAG_RE.finditer(text):
        try:
            obj = json.loads(match.group("json"))
        except (TypeError, ValueError):
            continue
        if isinstance(obj, dict):
            parsed = _normalize_json_tool(obj)
            if parsed:
                _add_call(calls, seen, parsed[0], parsed[1])
            elif "query" in obj:
                _add_call(calls, seen, match.group("name"), obj)

    for match in _PAREN_CALL_RE.finditer(text):
        name = match.group("name")
        if name in {"set_avatar_expression", "play_avatar_animation"} or "_" in name:
            _add_call(
                calls,
                seen,
                name,
                _parse_paren_args(name, match.group("body")),
            )

    for _start, _end, blob in _iter_json_objects(text):
        try:
            obj = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        parsed = _normalize_json_tool(obj)
        if parsed:
            _add_call(calls, seen, parsed[0], parsed[1])

    return calls


def strip_text_tool_calls(text: str) -> str:
    """Remove leaked tool-call syntax from spoken/display text."""
    body = (text or "").strip()
    if not body:
        return ""
    body = _STRIP_WRAPPED_CALL_RE.sub(" ", body)
    body = _STRIP_TOOL_JSON_RE.sub(" ", body)
    body = _STRIP_INLINE_CALL_RE.sub(" ", body)
    body = _STRIP_FUNCTION_TAG_RE.sub(" ", body)
    for _start, _end, blob in reversed(list(_iter_json_objects(body))):
        try:
            obj = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if isinstance(obj, dict) and _normalize_json_tool(obj):
            body = body[:_start] + " " + body[_end:]
    body = _STRIP_PAREN_CALL_RE.sub(" ", body)
    return re.sub(r"\s{2,}", " ", body).strip()
