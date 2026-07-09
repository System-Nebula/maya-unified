"""Optional dependency checks for game bridge."""

from __future__ import annotations


def check_game_bridge_deps() -> list[str]:
    """Return names of missing packages required for native capture + input."""
    missing: list[str] = []
    try:
        import mss  # noqa: F401
    except ImportError:
        missing.append("mss")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    try:
        import websocket  # noqa: F401
    except ImportError:
        missing.append("websocket-client")
    return missing


def check_vigem_available() -> bool:
    try:
        import vgamepad as vg

        pad = vg.VX360Gamepad()
        del pad
        return True
    except Exception:  # noqa: BLE001
        return False


def game_bridge_deps_message(missing: list[str] | None = None) -> str:
    items = missing if missing is not None else check_game_bridge_deps()
    if not items:
        return ""
    return (
        f"Game bridge dependencies missing ({', '.join(items)}). "
        "From maya-unified run: uv sync --extra game"
    )
