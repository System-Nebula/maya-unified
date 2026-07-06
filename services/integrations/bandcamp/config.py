"""Bandcamp integration configuration."""

from __future__ import annotations

import os


def default_username() -> str:
    return (os.getenv("MAYA_BANDCAMP_USERNAME") or "").strip()
