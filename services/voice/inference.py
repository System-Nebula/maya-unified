"""Shared lock for LLM/TTS inference (voice session + Discord clips)."""

from __future__ import annotations

import threading

INFERENCE_LOCK = threading.Lock()
