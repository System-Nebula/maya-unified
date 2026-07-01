"""Decode SillyTavern character cards embedded in PNG files.

Cards store base64-encoded JSON in PNG text chunks:
  - tEXt keyword ``chara`` — Character Card V2 (most common)
  - tEXt keyword ``ccv3`` — Character Card V3
  - zTXt — same keywords with zlib-compressed payload

Spec: https://github.com/bradennapier/character-cards-v2
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from typing import Any

from .character_card import normalize_import

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_CARD_KEYS = ("ccv3", "chara", "chara_card")


def _parse_text_payload(value: str) -> dict[str, Any]:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("empty chunk payload")
    if raw.startswith("{") or raw.startswith("["):
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("card JSON must be an object")
        return obj
    padded = raw + ("=" * (-len(raw) % 4))
    try:
        decoded = base64.b64decode(padded, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid base64 in PNG card chunk") from exc
    text = decoded.decode("utf-8")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("card JSON must be an object")
    return obj


def _read_text_chunk(chunk_data: bytes) -> tuple[str, str]:
    splitter = chunk_data.find(b"\x00")
    if splitter < 0:
        raise ValueError("malformed PNG text chunk")
    key = chunk_data[:splitter].decode("latin-1", errors="replace")
    value = chunk_data[splitter + 1 :].decode("latin-1", errors="replace")
    return key, value


def _read_ztxt_chunk(chunk_data: bytes) -> tuple[str, str]:
    splitter = chunk_data.find(b"\x00")
    if splitter < 0 or splitter + 2 >= len(chunk_data):
        raise ValueError("malformed PNG zTXt chunk")
    key = chunk_data[:splitter].decode("latin-1", errors="replace")
    comp_method = chunk_data[splitter + 1]
    zlib_data = chunk_data[splitter + 2 :]
    if comp_method != 0:
        raise ValueError(f"unsupported zTXt compression method {comp_method}")
    value = zlib.decompress(zlib_data).decode("latin-1", errors="replace")
    return key, value


def extract_png_text_chunks(png_bytes: bytes) -> dict[str, str]:
    """Return keyword -> text payload for all tEXt/zTXt chunks."""
    if not png_bytes.startswith(_PNG_SIG):
        raise ValueError("not a PNG file")
    out: dict[str, str] = {}
    offset = len(_PNG_SIG)
    while offset + 8 <= len(png_bytes):
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        offset += 4
        chunk_type = png_bytes[offset : offset + 4]
        offset += 4
        chunk_data = png_bytes[offset : offset + length]
        offset += length + 4  # CRC
        if chunk_type == b"tEXt":
            key, value = _read_text_chunk(chunk_data)
            out[key] = value
        elif chunk_type == b"zTXt":
            key, value = _read_ztxt_chunk(chunk_data)
            out[key] = value
        if chunk_type == b"IEND":
            break
    return out


def decode_card_from_png(png_bytes: bytes) -> dict[str, Any]:
    """Parse embedded SillyTavern card JSON from a PNG file."""
    chunks = extract_png_text_chunks(png_bytes)
    if not chunks:
        raise ValueError("no text metadata found in PNG")

    errors: list[str] = []
    for key in _CARD_KEYS:
        payload = chunks.get(key)
        if not payload:
            continue
        try:
            return _parse_text_payload(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{key}: {exc}")

    # Fallback: any chunk that parses as a card object.
    for key, payload in chunks.items():
        if key in {"Comment", "comment", "Description"}:
            continue
        try:
            obj = _parse_text_payload(payload)
            if isinstance(obj, dict) and (
                obj.get("spec") in ("chara_card_v2", "chara_card_v3")
                or obj.get("data")
                or "description" in obj
                or "personality" in obj
            ):
                return obj
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    detail = "; ".join(errors) if errors else "no chara/ccv3 chunk"
    raise ValueError(f"no character card data in PNG ({detail})")


def import_card_from_png(png_bytes: bytes) -> dict[str, Any]:
    """Decode PNG and return normalized character card fields."""
    return normalize_import(decode_card_from_png(png_bytes))
