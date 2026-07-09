"""Windows keyboard input — PostMessage to emulator only (no focus steal)."""

from __future__ import annotations

import logging
import sys
import time

from apps.game_bridge.input import InputBackend

log = logging.getLogger("game-bridge.input.win")

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

# Virtual-key codes for profile keymap targets
_VK: dict[str, int] = {
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "return": 0x0D,
    "enter": 0x0D,
    "backspace": 0x08,
    "x": 0x58,
    "z": 0x5A,
    "a": 0x41,
    "s": 0x53,
}

# Keys that need the extended bit in LPARAM (arrows, etc.)
_EXTENDED: set[str] = {"up", "down", "left", "right"}


def _find_hwnd(title_substring: str) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        needle = (title_substring or "").lower()
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
            title = (buf.value or "").lower()
            if needle in title:
                matches.append(int(hwnd))
            return True

        user32.EnumWindows(callback, 0)
        return matches[0] if matches else None
    except Exception as exc:  # noqa: BLE001
        log.warning("hwnd search failed: %s", exc)
        return None


def _normalize_key(key: str) -> str:
    aliases = {
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
        "return": "return",
        "enter": "return",
        "backspace": "backspace",
    }
    k = (key or "").strip()
    low = k.lower()
    return aliases.get(low, low if len(k) > 1 else k)


def _vk_for(key: str) -> int | None:
    norm = _normalize_key(key)
    if norm in _VK:
        return _VK[norm]
    if len(norm) == 1:
        return ord(norm.upper())
    return None


def _make_lparam(vk: int, *, key_up: bool = False, extended: bool = False) -> int:
    import ctypes

    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0) & 0xFF
    lp = 1 | (scan << 16)
    if extended:
        lp |= 1 << 24
    if key_up:
        lp |= (1 << 30) | (1 << 31)
    return lp


def _post_key(hwnd: int, vk: int, *, extended: bool = False) -> bool:
    import ctypes

    user32 = ctypes.windll.user32
    lp_down = _make_lparam(vk, extended=extended)
    lp_up = _make_lparam(vk, key_up=True, extended=extended)
    ok_down = bool(user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lp_down))
    time.sleep(0.03)
    ok_up = bool(user32.PostMessageW(hwnd, WM_KEYUP, vk, lp_up))
    return ok_down and ok_up


class WinKeyboardInput(InputBackend):
    """Send keys only to the emulator window — never steals focus or types globally."""

    def __init__(self, keymap: dict[str, str], *, title_substring: str = "mGBA") -> None:
        self._keymap = {k: v for k, v in keymap.items()}
        self._title = title_substring
        self._hwnd: int | None = None

    def bind_hwnd(self, hwnd: int | None) -> None:
        if hwnd:
            self._hwnd = int(hwnd)

    def _hwnd_for_press(self) -> int | None:
        if self._hwnd:
            import ctypes

            if ctypes.windll.user32.IsWindow(self._hwnd):
                return self._hwnd
            self._hwnd = None
        found = _find_hwnd(self._title)
        if found:
            self._hwnd = found
        return found

    def press(self, key: str) -> None:
        resolved = self._keymap.get(key, key)
        norm = _normalize_key(resolved)
        vk = _vk_for(resolved)
        hwnd = self._hwnd_for_press()
        if hwnd is None:
            log.warning("no emulator window for key %s", resolved)
            return
        if vk is None:
            log.warning("unknown vk for key %s (%s)", key, resolved)
            return

        extended = norm in _EXTENDED
        ok = _post_key(hwnd, vk, extended=extended)
        log.info(
            "sent key %s -> %s vk=0x%02X (hwnd=%s method=PostMessage ok=%s)",
            key,
            resolved,
            vk,
            hwnd,
            ok,
        )
        if not ok:
            log.warning("PostMessage failed for %s — is mGBA still open?", resolved)
