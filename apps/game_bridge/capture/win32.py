"""Win32 window capture via mss."""

from __future__ import annotations

import base64
import logging
import sys
from io import BytesIO

log = logging.getLogger("game-bridge.capture.win32")


class Win32Capture:
    def __init__(self, *, title_substring: str = "mGBA", **_kw) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Win32Capture requires Windows")
        self._title = title_substring
        self._hwnd: int | None = None

    def _find_hwnd(self) -> int | None:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            matches: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def callback(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value or ""
                if self._title.lower() in title.lower():
                    matches.append(int(hwnd))
                return True

            user32.EnumWindows(callback, 0)
            return matches[0] if matches else None
        except Exception as exc:  # noqa: BLE001
            log.warning("hwnd search failed: %s", exc)
            return None

    def _rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        """Client area in screen coords (excludes title bar / FPS text)."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            rect = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return None
            pt = wintypes.POINT(0, 0)
            if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                return None
            left, top = pt.x, pt.y
            right = left + rect.right
            bottom = top + rect.bottom
            if right - left < 8 or bottom - top < 8:
                return None
            return left, top, right, bottom
        except Exception:
            return None

    def capture_png_base64(self) -> str | None:
        try:
            import mss
            from PIL import Image
        except ImportError as exc:
            log.error("mss/Pillow required for Win32 capture: %s", exc)
            return None

        hwnd = self._hwnd or self._find_hwnd()
        if hwnd is None:
            log.warning("no window matching %r", self._title)
            return None
        self._hwnd = hwnd
        box = self._rect(hwnd)
        if box is None:
            return None
        left, top, right, bottom = box
        w, h = right - left, bottom - top
        if w < 8 or h < 8:
            return None
        with mss.mss() as sct:
            shot = sct.grab({"left": left, "top": top, "width": w, "height": h})
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def close(self) -> None:
        self._hwnd = None
