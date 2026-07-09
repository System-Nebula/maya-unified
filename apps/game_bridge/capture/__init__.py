"""Capture backends for game bridge."""

from __future__ import annotations

from abc import ABC, abstractmethod


class CaptureBackend(ABC):
    @abstractmethod
    def capture_png_base64(self) -> str | None:
        """Return raw base64 PNG bytes (no data: prefix) or None."""

    def close(self) -> None:
        return None


def create_capture(backend: str, **opts) -> CaptureBackend:
    name = (backend or "browser_share").lower()
    if name == "native_window" or name == "win32":
        import sys

        if sys.platform == "win32":
            from apps.game_bridge.capture.win32 import Win32Capture

            return Win32Capture(**opts)
        if _is_wayland():
            from apps.game_bridge.capture.wayland import WaylandCapture

            return WaylandCapture(**opts)
        from apps.game_bridge.capture.browser import BrowserCapture

        return BrowserCapture(**opts)
    if name == "wayland":
        from apps.game_bridge.capture.wayland import WaylandCapture

        return WaylandCapture(**opts)
    from apps.game_bridge.capture.browser import BrowserCapture

    return BrowserCapture(**opts)


def _is_wayland() -> bool:
    import os

    return (os.environ.get("XDG_SESSION_TYPE") or "").lower() == "wayland"
