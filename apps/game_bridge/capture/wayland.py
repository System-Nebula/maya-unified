"""Wayland capture via grim (region) or full screen fallback."""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("game-bridge.capture.wayland")


class WaylandCapture:
    def __init__(self, *, title_substring: str = "", **_kw) -> None:
        self._title = title_substring

    def capture_png_base64(self) -> str | None:
        if (os.environ.get("XDG_SESSION_TYPE") or "").lower() != "wayland":
            log.warning("WaylandCapture used outside Wayland session")
        for cmd in (
            ["grim", "-g", "0,0 640x480", "-"],
            ["grim", "-"],
        ):
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=8, check=False)
                if proc.returncode == 0 and proc.stdout and len(proc.stdout) > 64:
                    return base64.b64encode(proc.stdout).decode("ascii")
            except FileNotFoundError:
                log.error("grim not found — install grim or use browser_share capture")
                return None
            except Exception as exc:  # noqa: BLE001
                log.debug("grim failed %s: %s", cmd, exc)
        # portal fallback: write temp file
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                path = Path(tmp.name)
            proc = subprocess.run(["grim", str(path)], capture_output=True, timeout=8, check=False)
            if proc.returncode == 0 and path.is_file():
                data = path.read_bytes()
                path.unlink(missing_ok=True)
                if len(data) > 64:
                    return base64.b64encode(data).decode("ascii")
        except Exception as exc:  # noqa: BLE001
            log.warning("wayland capture failed: %s", exc)
        return None
