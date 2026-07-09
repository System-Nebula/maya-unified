"""ViGEm virtual Xbox 360 gamepad — background-safe when ViGEmBus is installed."""

from __future__ import annotations

import logging
import time

from apps.game_bridge.input import InputBackend

log = logging.getLogger("game-bridge.input.vigem")

# Logical button -> vgamepad XUSB button name
_XUSB_MAP: dict[str, str] = {
    "a": "XUSB_GAMEPAD_A",
    "b": "XUSB_GAMEPAD_B",
    "x": "XUSB_GAMEPAD_X",
    "y": "XUSB_GAMEPAD_Y",
    "start": "XUSB_GAMEPAD_START",
    "back": "XUSB_GAMEPAD_BACK",
    "select": "XUSB_GAMEPAD_BACK",
    "up": "XUSB_GAMEPAD_DPAD_UP",
    "down": "XUSB_GAMEPAD_DPAD_DOWN",
    "left": "XUSB_GAMEPAD_DPAD_LEFT",
    "right": "XUSB_GAMEPAD_DPAD_RIGHT",
}

_PAD: object | None = None


def _pad():
    global _PAD  # noqa: PLW0603
    if _PAD is not None:
        return _PAD
    import vgamepad as vg

    _PAD = vg.VX360Gamepad()
    return _PAD


class ViGEmGamepadInput(InputBackend):
    """Virtual gamepad taps — mGBA reads controller input without keyboard focus."""

    def __init__(self, keymap: dict[str, str], **_kw) -> None:
        self._keymap = {k: v for k, v in keymap.items()}

    def bind_hwnd(self, _hwnd: int | None) -> None:
        return

    def press(self, key: str) -> None:
        import vgamepad as vg

        target = self._keymap.get(key, key).strip().lower()
        xusb_name = _XUSB_MAP.get(target)
        if not xusb_name:
            log.warning("no gamepad mapping for %s (%s)", key, target)
            return
        button = getattr(vg.XUSB_BUTTON, xusb_name, None)
        if button is None:
            log.warning("unknown XUSB button %s", xusb_name)
            return
        pad = _pad()
        pad.press_button(button)
        pad.update()
        time.sleep(0.05)
        pad.release_button(button)
        pad.update()
        log.info("sent gamepad %s -> %s", key, xusb_name)
