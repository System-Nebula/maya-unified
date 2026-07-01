"""Resolve the voice owner's display name from USER.md for {{user}} substitution."""

from __future__ import annotations

import os
import re

_NAME_PATTERNS = (
    re.compile(
        r"(?:user(?:'s)?\s+name\s+is|call(?:s)?\s+(?:the\s+)?user|call\s+them)\s+"
        r"([A-Za-z][A-Za-z0-9' -]{0,40}?)(?:\s*,|\s+the\b|\.|$)",
        re.I,
    ),
    re.compile(
        r"claims?\s+to\s+be\s+([A-Za-z][A-Za-z0-9' -]{0,40}?)(?:\s*,|\s+the\b|\.|$)",
        re.I,
    ),
    re.compile(r"^Name:\s*(.+?)\s*$", re.I | re.M),
    re.compile(
        r"^The user is\s+([A-Za-z][A-Za-z0-9' -]{0,40}?)(?:\s*,|\s+the\b|\.|$)",
        re.I | re.M,
    ),
)


def _user_md_path(data_dir: str) -> str:
    return os.path.join(data_dir, "memory", "USER.md")


def _read_entries(data_dir: str) -> list[str]:
    path = _user_md_path(data_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return []
    return [e.strip() for e in raw.split("§") if e.strip()]


def resolve_user_name(data_dir: str, default: str = "the user") -> str:
    """Best-effort name from USER.md entries (e.g. 'claims to be Miles')."""
    for entry in _read_entries(data_dir):
        for pattern in _NAME_PATTERNS:
            match = pattern.search(entry)
            if not match:
                continue
            name = (match.group(1) or "").strip().strip("\"'")
            if name and name.lower() not in {"the user", "user", "unknown"}:
                return name
    return default
