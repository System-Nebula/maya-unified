"""In-memory stash of latest browser screen-share frames per operator."""

from __future__ import annotations

import base64
import binascii
import re
import time
from dataclasses import dataclass
from io import BytesIO

MAX_FRAME_BYTES = 1_500_000
TTL_S = 45.0
MAX_EDGE_PX = 2048

_DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,(.+)$", re.I | re.S)


@dataclass
class VisionFrame:
    data_url: str
    captured_at: float
    label: str = ""


_frames: dict[str, VisionFrame] = {}


def _decode_image_bytes(image: str) -> bytes | None:
    raw = (image or "").strip()
    if not raw:
        return None
    match = _DATA_URL_RE.match(raw)
    if match:
        b64 = match.group(2).strip()
    else:
        b64 = raw
    b64 = re.sub(r"\s+", "", b64)
    pad = (-len(b64)) % 4
    if pad:
        b64 += "=" * pad
    try:
        return base64.b64decode(b64, validate=False)
    except (ValueError, binascii.Error):
        return None


def _reencode_png(image: str) -> str | None:
    """Decode any supported browser frame and re-encode as PNG for LM Studio."""
    blob = _decode_image_bytes(image)
    if not blob or len(blob) < 32:
        return None
    try:
        from PIL import Image
    except ImportError:
        mime = "image/jpeg"
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif not blob.startswith(b"\xff\xd8\xff"):
            return None
        b64 = base64.b64encode(blob).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        if len(data_url.encode("utf-8")) > MAX_FRAME_BYTES:
            return None
        return data_url

    try:
        img = Image.open(BytesIO(blob))
        img.load()
    except Exception:
        return None
    w, h = img.size
    if max(w, h) > MAX_EDGE_PX:
        scale = MAX_EDGE_PX / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    elif img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    png_bytes = out.getvalue()
    if len(png_bytes) > MAX_FRAME_BYTES:
        return None
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _normalize_data_url(image: str) -> str | None:
    return _reencode_png(image)


def put_frame(operator_id: str, image: str, *, label: str = "") -> dict:
    oid = str(operator_id or "").strip()
    if not oid:
        return {"ok": False, "error": "missing operator"}
    data_url = _normalize_data_url(image)
    if not data_url:
        return {"ok": False, "error": "invalid or oversized frame"}
    _frames[oid] = VisionFrame(
        data_url=data_url,
        captured_at=time.monotonic(),
        label=(label or "").strip(),
    )
    return {"ok": True}


def get_frame(operator_id: str | None) -> str | None:
    oid = str(operator_id or "").strip()
    if not oid:
        return None
    frame = _frames.get(oid)
    if frame is None:
        return None
    if (time.monotonic() - frame.captured_at) > TTL_S:
        _frames.pop(oid, None)
        return None
    return frame.data_url


def clear_frame(operator_id: str | None) -> None:
    oid = str(operator_id or "").strip()
    if oid:
        _frames.pop(oid, None)


def status_for(operator_id: str | None) -> dict:
    oid = str(operator_id or "").strip()
    if not oid:
        return {"active": False, "label": "", "age_ms": None}
    frame = _frames.get(oid)
    if frame is None:
        return {"active": False, "label": "", "age_ms": None}
    age_ms = int((time.monotonic() - frame.captured_at) * 1000)
    if age_ms > int(TTL_S * 1000):
        _frames.pop(oid, None)
        return {"active": False, "label": "", "age_ms": None}
    return {"active": True, "label": frame.label, "age_ms": age_ms}
