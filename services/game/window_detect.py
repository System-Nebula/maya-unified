"""Detect emulator windows for dashboard game mode."""

from __future__ import annotations

import sys
from typing import Any


def list_matching_windows(title_substring: str) -> list[dict[str, Any]]:
    """Return visible windows whose title contains title_substring (case-insensitive)."""
    needle = (title_substring or "").strip().lower()
    if not needle:
        return []
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        matches: list[dict[str, Any]] = []

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
            if needle not in title.lower():
                return True
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                w = rect.right - rect.left
                h = rect.bottom - rect.top
            else:
                w = h = 0
            matches.append(
                {
                    "hwnd": int(hwnd),
                    "title": title,
                    "width": w,
                    "height": h,
                }
            )
            return True

        user32.EnumWindows(callback, 0)
        matches.sort(key=lambda m: m.get("title") or "")
        return matches
    except Exception:  # noqa: BLE001
        return []
