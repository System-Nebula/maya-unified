"""Browser-share capture — POST frames to Maya /api/game/frame."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

log = logging.getLogger("game-bridge.capture.browser")


class BrowserCapture:
    """Placeholder when native capture unavailable — operator shares via dashboard."""

    def __init__(self, **_) -> None:
        self._last_path: Path | None = None

    def capture_png_base64(self) -> str | None:
        return None

    @staticmethod
    def upload_http(
        *,
        gateway: str,
        token: str,
        image_b64_or_data_url: str,
        session_id: str | None = None,
        label: str = "",
    ) -> dict:
        url = f"{gateway.rstrip('/')}/api/game/frame"
        headers = {"Cookie": f"maya_op_session={token}"}
        body: dict = {"image": image_b64_or_data_url, "label": label}
        if session_id:
            body["session_id"] = session_id
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def file_to_data_url(path: Path) -> str:
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/png;base64,{b64}"
