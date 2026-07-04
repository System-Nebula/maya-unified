"""Bridge to external Model Context Protocol (MCP) stdio servers.

Reads a JSON config of stdio servers, launches each, lists its tools, and exposes
them as `ToolSpec`s the agent loop can call like any built-in tool.

The official `mcp` SDK is asyncio-based; the voice agent is synchronous/threaded,
so we run a dedicated event loop on a background thread and submit coroutines to
it with `run_coroutine_threadsafe`. The module is named `mcp_bridge` (not `mcp`)
so it never shadows the installed `mcp` package.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Optional

from .registry import ToolSpec

# Commands that are batch scripts on Windows and must run via cmd /c.
_WIN_WRAP = {"npx", "npm", "npm.cmd", "yarn", "pnpm", "node", "uvx", "uv", "bunx"}

_PACKAGE_MISSING_MSG = "mcp package not installed — run: uv sync --extra mcp"


def resolve_mcp_config_path(path: str) -> str:
    """Resolve MCP config relative to voice-runtime (matches services.paths.resolve_runtime_file)."""
    raw = (path or "").strip()
    if not raw:
        return raw
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, raw)
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)
    if os.path.isabs(raw):
        return raw
    return os.path.abspath(candidate)


def _mcp_package_installed() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _load_config(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError) as exc:
        print(f"[mcp] could not read {path}: {exc}")
        return {}


class MCPManager:
    """Owns the MCP event loop, sessions, and the tools they expose."""

    def __init__(self, config_path: str, startup_timeout: float = 30.0):
        self.config_path = config_path
        self.startup_timeout = startup_timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._sessions: dict[str, Any] = {}
        self._stack = None
        self._server_status: dict[str, dict] = {}
        self._meta: dict[str, Any] = {}

    # ----- lifecycle --------------------------------------------------------

    def _set_meta(self, **fields: Any) -> None:
        self._meta.update(fields)

    def _mark_servers_unavailable(self, names: dict, *, error: str) -> None:
        for name in names:
            self._server_status[name] = {"connected": False, "error": error}

    def _build_hint(self) -> str | None:
        if self._meta.get("config_missing"):
            return (
                f"MCP config not found at {self.config_path}. "
                "Copy mcp_servers.json.example to mcp_servers.json and restart."
            )
        if self._meta.get("no_servers_configured"):
            return "No MCP servers enabled in mcp_servers.json."
        if self._meta.get("package_missing"):
            return f"MCP package not installed. Run `uv sync --extra mcp` and restart the gateway."
        failed = [
            name
            for name, st in self._server_status.items()
            if not st.get("connected")
        ]
        if failed and not any(st.get("connected") for st in self._server_status.values()):
            first = failed[0]
            err = (self._server_status.get(first) or {}).get("error") or "not connected"
            return f"{first} — not connected: {err}"
        return None

    def start(self) -> list[ToolSpec]:
        """Launch configured servers and return their tools (empty on any issue)."""
        self._meta = {"config_path": self.config_path}

        if not os.path.isfile(self.config_path):
            self._set_meta(config_missing=True)
            print(f"[mcp] config not found: {self.config_path}")
            return []

        cfg = _load_config(self.config_path)
        servers = cfg.get("servers", {})
        enabled = {n: c for n, c in servers.items() if c.get("enabled", True)}
        if not enabled:
            self._set_meta(no_servers_configured=True)
            return []

        if not _mcp_package_installed():
            self._set_meta(package_missing=True, package_installed=False)
            self._mark_servers_unavailable(enabled, error=_PACKAGE_MISSING_MSG)
            print("[mcp] the 'mcp' package is not installed; skipping MCP servers. "
                  "Install with: uv sync --extra mcp")
            return []

        self._set_meta(package_installed=True)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        specs: list[ToolSpec] = []
        for name, conf in enabled.items():
            try:
                tools = self._submit(self._connect_server(name, conf), self.startup_timeout)
                specs.extend(tools)
                self._server_status[name] = {"connected": True, "tools": len(tools)}
                print(f"[mcp] connected '{name}' ({len(tools)} tools)")
            except Exception as exc:  # noqa: BLE001 - one bad server must not kill the rest
                self._server_status[name] = {"connected": False, "error": str(exc)}
                print(f"[mcp] failed to start '{name}': {exc}")
        return specs

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro, timeout: float):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _connect_server(self, name: str, conf: dict) -> list[ToolSpec]:
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if self._stack is None:
            self._stack = AsyncExitStack()

        command = conf.get("command", "")
        args = list(conf.get("args", []))
        if os.name == "nt" and command.lower() in _WIN_WRAP:
            args = ["/c", command, *args]
            command = "cmd"

        env = {**os.environ, **(conf.get("env") or {})}
        params = StdioServerParameters(command=command, args=args, env=env)

        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[name] = session

        listed = await session.list_tools()
        specs: list[ToolSpec] = []
        for tool in listed.tools:
            specs.append(self._make_spec(name, session, tool))
        return specs

    def _make_spec(self, server: str, session, tool) -> ToolSpec:
        # Namespace the tool so two servers can expose the same tool name.
        qualified = f"{server}__{tool.name}"
        schema = tool.inputSchema or {"type": "object", "properties": {}}

        def handler(args: dict, _name=tool.name, _session=session) -> str:
            return self._submit(self._call_tool(_session, _name, args),
                                timeout=self.startup_timeout)

        return ToolSpec(
            name=qualified,
            description=(tool.description or f"{tool.name} (via {server})").strip(),
            parameters=schema,
            handler=handler,
            group=f"mcp:{server}",
        )

    @staticmethod
    async def _call_tool(session, name: str, args: dict) -> str:
        result = await session.call_tool(name, args or {})
        parts: list[str] = []
        for item in (result.content or []):
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(text)
                continue
            image_url = MCPManager._save_image_content(item)
            if image_url:
                parts.append(f"Saved image: {image_url}")
                continue
            parts.append(str(item))
        out = "\n".join(parts).strip() or "ok"
        if getattr(result, "isError", False):
            return f"error: {out}"
        return out

    @staticmethod
    def _save_image_content(item) -> str | None:
        """Persist MCP ImageContent to blender-outputs and return a gateway URL."""
        typ = getattr(item, "type", None)
        if typ != "image" and not (isinstance(item, dict) and item.get("type") == "image"):
            data = getattr(item, "data", None)
            if data is None:
                return None
        try:
            from services.artifacts.store import artifact_url_for_path, save_image_bytes
            from services.blender.client import _content_item_image_bytes

            raw = _content_item_image_bytes(item)
            if not raw:
                return None
            path = save_image_bytes(raw)
            return artifact_url_for_path(path)
        except Exception:  # noqa: BLE001
            return None

    def status(self) -> dict:
        if "package_installed" in self._meta:
            package_installed = bool(self._meta["package_installed"])
        else:
            package_installed = _mcp_package_installed()
        hint = self._build_hint()
        connected = sum(1 for st in self._server_status.values() if st.get("connected"))
        return {
            "servers": self._server_status,
            "config_path": self.config_path,
            "package_installed": package_installed,
            "connected_count": connected,
            "hint": hint,
        }

    def close(self) -> None:
        if self._loop is None:
            return
        try:
            if self._stack is not None:
                fut = asyncio.run_coroutine_threadsafe(self._stack.aclose(), self._loop)
                try:
                    fut.result(timeout=5.0)
                except Exception:  # noqa: BLE001
                    pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:  # noqa: BLE001
            pass
