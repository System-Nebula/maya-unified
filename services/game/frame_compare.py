"""Compare game frames — detect stale/wrong screen before executing actions."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO


def hash_png_base64(b64: str) -> str:
    """Stable hash of raw PNG bytes (ignores data: URL prefix)."""
    payload = (b64 or "").strip()
    if "," in payload:
        payload = payload.split(",", 1)[1]
    return hashlib.sha256(payload.encode("ascii")).hexdigest()[:16]


def _decode_png(b64: str) -> bytes | None:
    payload = (b64 or "").strip()
    if not payload:
        return None
    if "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        return base64.b64decode(payload)
    except Exception:  # noqa: BLE001
        return None


def frame_similarity(b64_a: str, b64_b: str, *, size: int = 96) -> float:
    """Return 1.0 = identical, 0.0 = totally different (downscaled grayscale MSE)."""
    raw_a = _decode_png(b64_a)
    raw_b = _decode_png(b64_b)
    if not raw_a or not raw_b:
        return 0.0
    if raw_a == raw_b:
        return 1.0
    try:
        from PIL import Image
    except ImportError:
        return 1.0 if hash_png_base64(b64_a) == hash_png_base64(b64_b) else 0.0

    try:
        img_a = Image.open(BytesIO(raw_a)).convert("L").resize((size, size))
        img_b = Image.open(BytesIO(raw_b)).convert("L").resize((size, size))
    except Exception:  # noqa: BLE001
        return 0.0

    pixels_a = list(img_a.getdata())
    pixels_b = list(img_b.getdata())
    if len(pixels_a) != len(pixels_b) or not pixels_a:
        return 0.0
    mse = sum((a - b) ** 2 for a, b in zip(pixels_a, pixels_b, strict=True)) / len(pixels_a)
    # Max MSE for 8-bit grayscale is 255^2 = 65025
    return max(0.0, 1.0 - (mse / 65025.0))


def frame_stable_enough(
    reference_b64: str,
    current_b64: str,
    *,
    min_similarity: float = 0.82,
) -> tuple[bool, float]:
    """True when current frame still matches the reference shown to the vision model."""
    sim = frame_similarity(reference_b64, current_b64)
    return sim >= min_similarity, sim
