"""On-demand stdio MCP client for blender-mcp."""

from __future__ import annotations

import base64
import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_COMMAND = "/home/warby/.local/bin/blender-mcp"
_WIN_WRAP = {"npx", "npm", "npm.cmd", "yarn", "pnpm", "node", "uvx", "uv", "bunx"}


@dataclass
class BlenderToolResult:
    text: str = ""
    images: list[bytes] = field(default_factory=list)
    is_error: bool = False


def _resolve_blender_mcp_config() -> tuple[str, list[str], dict[str, str]]:
    env_override = os.environ.get("MAYA_BLENDER_MCP_COMMAND", "").strip()
    command = env_override or _DEFAULT_COMMAND
    args: list[str] = []
    env = dict(os.environ)

    if not env_override:
        config_path = Path(__file__).resolve().parents[2] / "packages" / "voice-runtime" / "mcp_servers.json"
        if config_path.is_file():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                conf = (data.get("servers") or {}).get("blender") or {}
                if conf.get("command"):
                    command = str(conf["command"])
                if conf.get("args"):
                    args = [str(a) for a in conf["args"]]
                if conf.get("env"):
                    env.update({str(k): str(v) for k, v in conf["env"].items()})
            except (OSError, ValueError, TypeError):
                pass

    if os.name == "nt" and command.lower() in _WIN_WRAP:
        args = ["/c", command, *args]
        command = "cmd"
    return command, args, env


def _content_item_type(item: Any) -> str:
    typ = getattr(item, "type", None)
    if typ:
        return str(typ)
    if isinstance(item, dict):
        return str(item.get("type") or "")
    return ""


def _content_item_text(item: Any) -> str | None:
    text = getattr(item, "text", None)
    if text is not None:
        return str(text)
    if isinstance(item, dict) and item.get("text") is not None:
        return str(item["text"])
    return None


def _content_item_image_bytes(item: Any) -> bytes | None:
    data = getattr(item, "data", None)
    if data is None and isinstance(item, dict):
        data = item.get("data")
    if not data:
        return None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    try:
        return base64.b64decode(str(data))
    except Exception:  # noqa: BLE001
        return None


def parse_tool_result(result: Any) -> BlenderToolResult:
    parts: list[str] = []
    images: list[bytes] = []
    for item in (getattr(result, "content", None) or []):
        text = _content_item_text(item)
        if text is not None:
            parts.append(text)
            continue
        if _content_item_type(item) == "image":
            raw = _content_item_image_bytes(item)
            if raw:
                images.append(raw)
                continue
        raw = _content_item_image_bytes(item)
        if raw:
            images.append(raw)
        else:
            parts.append(str(item))
    out = "\n".join(parts).strip()
    is_error = bool(getattr(result, "isError", False))
    if is_error and not out:
        out = "error"
    return BlenderToolResult(text=out or ("ok" if not is_error else "error"), images=images, is_error=is_error)


async def call_blender_tool(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    timeout: float = 120.0,
) -> BlenderToolResult:
    """Connect to blender-mcp, call one tool, and tear down."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command, cmd_args, env = _resolve_blender_mcp_config()
    params = StdioServerParameters(command=command, args=cmd_args, env=env)

    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        result = await session.call_tool(name, args or {})
        return parse_tool_result(result)


def call_blender_tool_sync(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    timeout: float = 120.0,
) -> BlenderToolResult:
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(call_blender_tool(name, args, timeout=timeout))
    if loop.is_running():
        raise RuntimeError("call_blender_tool_sync cannot run inside an active event loop")
    return loop.run_until_complete(call_blender_tool(name, args, timeout=timeout))
