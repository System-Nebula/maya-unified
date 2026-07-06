"""Parse slash-style cmd input."""

from __future__ import annotations

import shlex
from typing import Any

from services.cmd.models import CmdDefinition, ParsedCmd
from services.cmd.registry import registry


def is_cmd_input(text: str) -> bool:
    return (text or "").lstrip().startswith("/")


def parse_cmd_input(text: str) -> ParsedCmd | None:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    body = raw[1:].strip()
    if not body:
        return None
    try:
        parts = shlex.split(body)
    except ValueError:
        parts = body.split()
    if not parts:
        return None
    name = parts[0]
    cmd = registry.resolve(name)
    if cmd is None:
        return None
    raw_args = body[len(name) :].strip()
    args = _derive_args(cmd, parts[1:], raw_args)
    return ParsedCmd(cmd_id=cmd.id, name=cmd.name, raw_args=raw_args, args=args)


def validate_args(cmd: CmdDefinition, args: dict[str, Any]) -> str | None:
    for param in cmd.parameters:
        if param.required and param.name not in args:
            return f"missing required parameter: {param.name}"
        if param.name in args and param.allowed_values():
            value = str(args[param.name])
            if value not in param.allowed_values():
                allowed = ", ".join(param.allowed_values())
                return f"invalid value for {param.name}: {value!r} (allowed: {allowed})"
    return None


def _derive_args(cmd: CmdDefinition, tokens: list[str], raw_args: str) -> dict[str, Any]:
    if not cmd.parameters:
        if raw_args:
            return {"prompt": raw_args}
        return {}

    required = [p for p in cmd.parameters if p.required]
    optional = [p for p in cmd.parameters if not p.required]

    if len(required) == 1 and required[0].type == "string" and raw_args:
        prompt_text, kv = _split_prompt_and_kv(raw_args, cmd)
        out: dict[str, Any] = dict(kv)
        if prompt_text:
            out[required[0].name] = prompt_text
        elif required[0].name not in out:
            out[required[0].name] = raw_args
    else:
        out = {}
        ordered = required + optional
        for idx, token in enumerate(tokens):
            if idx >= len(ordered):
                break
            out[ordered[idx].name] = _coerce(token, ordered[idx].type)

    for param in cmd.parameters:
        if param.name in out:
            continue
        if param.default is not None:
            out[param.name] = param.default

    return out


def _split_prompt_and_kv(raw_args: str, cmd: CmdDefinition) -> tuple[str, dict[str, Any]]:
    """Split `sunset model=krea2` into prompt text and named cmd parameters."""
    param_by_name = {p.name: p for p in cmd.parameters}
    try:
        tokens = shlex.split(raw_args)
    except ValueError:
        tokens = raw_args.split()

    kv: dict[str, Any] = {}
    prompt_parts: list[str] = []
    for token in tokens:
        key, sep, value = token.partition("=")
        if sep and key in param_by_name:
            kv[key] = _coerce(value, param_by_name[key].type)
        else:
            prompt_parts.append(token)

    return " ".join(prompt_parts).strip(), kv


def _coerce(value: str, typ: str) -> Any:
    if typ == "integer":
        return int(value)
    if typ == "number":
        return float(value)
    if typ == "boolean":
        return value.lower() in {"1", "true", "yes", "on"}
    return value
