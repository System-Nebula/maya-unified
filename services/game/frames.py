"""Fast frame stash for game-mode vision (per operator + session)."""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass

from services.voice import vision_frames as _vf

MAX_EDGE_PX = 640
TTL_S = 15.0


@dataclass
class GameFrame:
    data_url: str
    captured_at: float
    frame_seq: int
    content_hash: str
    label: str = ""


_frames: dict[str, GameFrame] = {}
_seq: dict[str, int] = {}


def _key(operator_id: str, session_id: str | None = None) -> str:
    oid = str(operator_id or "").strip()
    sid = str(session_id or "default").strip() or "default"
    return f"{oid}:{sid}"


def _hash_data_url(data_url: str) -> str:
    return hashlib.sha256(data_url.encode("utf-8")).hexdigest()[:16]


def put_frame(
    operator_id: str,
    image: str,
    *,
    session_id: str | None = None,
    label: str = "",
    max_edge: int = MAX_EDGE_PX,
) -> dict:
    oid = str(operator_id or "").strip()
    if not oid:
        return {"ok": False, "error": "missing operator"}
    # Reuse vision frame normalizer; game stash uses smaller max edge via pre-scale in caller
    result = _vf.put_frame(oid, image, label=label)
    if not result.get("ok"):
        return result
    data_url = _vf.get_frame(oid)
    if not data_url:
        return {"ok": False, "error": "frame rejected"}
    key = _key(oid, session_id)
    _seq[key] = _seq.get(key, 0) + 1
    frame = GameFrame(
        data_url=data_url,
        captured_at=time.monotonic(),
        frame_seq=_seq[key],
        content_hash=_hash_data_url(data_url),
        label=(label or "").strip(),
    )
    _frames[key] = frame
    return {
        "ok": True,
        "frame_seq": frame.frame_seq,
        "content_hash": frame.content_hash,
    }


def get_frame(operator_id: str | None, *, session_id: str | None = None) -> GameFrame | None:
    key = _key(operator_id or "", session_id)
    frame = _frames.get(key)
    if frame is None:
        return None
    if (time.monotonic() - frame.captured_at) > TTL_S:
        _frames.pop(key, None)
        return None
    return frame


def get_data_url(operator_id: str | None, *, session_id: str | None = None) -> str | None:
    frame = get_frame(operator_id, session_id=session_id)
    return frame.data_url if frame else None


def frame_changed(
    operator_id: str | None,
    *,
    session_id: str | None = None,
    since_hash: str | None = None,
) -> bool:
    frame = get_frame(operator_id, session_id=session_id)
    if frame is None:
        return False
    if not since_hash:
        return True
    return frame.content_hash != since_hash


def clear_frame(operator_id: str | None, *, session_id: str | None = None) -> None:
    key = _key(operator_id or "", session_id)
    _frames.pop(key, None)
    _vf.clear_frame(operator_id)


def status_for(operator_id: str | None, *, session_id: str | None = None) -> dict:
    frame = get_frame(operator_id, session_id=session_id)
    if frame is None:
        return {"active": False, "frame_seq": 0, "age_ms": None, "label": ""}
    age_ms = int((time.monotonic() - frame.captured_at) * 1000)
    return {
        "active": True,
        "frame_seq": frame.frame_seq,
        "content_hash": frame.content_hash,
        "age_ms": age_ms,
        "label": frame.label,
    }


def frame_ref(operator_id: str, session_id: str | None = None) -> str:
    """Opaque ref passed in actions/force — resolved server-side."""
    sid = str(session_id or "default")
    return f"game:{operator_id}:{sid}"


def resolve_frame_bytes(frame_ref: str) -> bytes | None:
    """Decode PNG bytes from a game frame_ref (game:operator:session)."""
    ref = (frame_ref or "").strip()
    if not ref.startswith("game:"):
        return None
    parts = ref.split(":", 2)
    if len(parts) != 3:
        return None
    _, operator_id, session_id = parts
    data_url = get_data_url(operator_id, session_id=session_id)
    if not data_url:
        return None
    payload = data_url
    if "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        return base64.b64decode(payload)
    except Exception:  # noqa: BLE001
        return None
