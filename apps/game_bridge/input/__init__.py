"""Keyboard input backends."""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod


class InputBackend(ABC):
    @abstractmethod
    def press(self, key: str) -> None:
        pass

    def wait_ms(self, ms: int) -> None:
        import time

        time.sleep(max(0, ms) / 1000.0)


def create_input(backend: str, keymap: dict[str, str], *, title_substring: str = "mGBA") -> InputBackend:
    name = (backend or "keyboard").lower().replace("-", "_")

    if name in {"gamepad_vigem", "vigem", "gamepad"}:
        from apps.game_bridge.input.gamepad_vigem import ViGEmGamepadInput

        return ViGEmGamepadInput(keymap, title_substring=title_substring)

    if name != "keyboard":
        raise ValueError(f"unsupported input backend: {backend}")

    if sys.platform == "win32":
        from apps.game_bridge.input.keyboard_win import WinKeyboardInput

        return WinKeyboardInput(keymap, title_substring=title_substring)
    if (os.environ.get("XDG_SESSION_TYPE") or "").lower() == "wayland":
        from apps.game_bridge.input.keyboard_wayland import WaylandKeyboardInput

        return WaylandKeyboardInput(keymap)
    from apps.game_bridge.input.keyboard_win import WinKeyboardInput

    return WinKeyboardInput(keymap)
