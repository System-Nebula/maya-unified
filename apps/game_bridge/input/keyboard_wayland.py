"""Wayland keyboard input via wtype or ydotool."""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("game-bridge.input.wayland")

# Map common key names to wtype keys
_WTYPE_KEYS = {
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
    "Return": "return",
    "BackSpace": "backspace",
    "Escape": "escape",
}


class WaylandKeyboardInput:
    def __init__(self, keymap: dict[str, str]) -> None:
        self._keymap = dict(keymap)
        self._wtype = shutil.which("wtype")
        self._ydotool = shutil.which("ydotool")

    def press(self, key: str) -> None:
        resolved = self._keymap.get(key, key)
        if self._wtype and resolved in _WTYPE_KEYS:
            subprocess.run([self._wtype, "-k", _WTYPE_KEYS[resolved]], check=False, timeout=3)
            return
        if self._wtype and len(resolved) == 1:
            subprocess.run([self._wtype, resolved], check=False, timeout=3)
            return
        if self._ydotool:
            # ydotool key codes vary — best-effort for letters
            if len(resolved) == 1:
                code = ord(resolved.lower()) - ord("a") + 30
                subprocess.run([self._ydotool, "key", f"{code}:1", f"{code}:0"], check=False, timeout=3)
                return
        log.warning("could not press key %r on Wayland (install wtype or ydotool)", resolved)
