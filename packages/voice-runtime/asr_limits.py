"""Shared limits/helpers for scripts/asr_server.py (ASR-003) — no GPU imports."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

MAX_UPLOAD_BYTES = int(os.environ.get("VA_ASR_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
MAX_DURATION_S = float(os.environ.get("VA_ASR_MAX_DURATION_S", "120"))
READ_CHUNK_BYTES = 64 * 1024


class UploadTooLarge(ValueError):
    def __init__(self, message: str, *, status_code: int = 413) -> None:
        super().__init__(message)
        self.status_code = status_code


def enforce_upload_size(nbytes: int, *, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
    if nbytes > max_bytes:
        raise UploadTooLarge(f"upload too large ({nbytes} bytes > {max_bytes})")


def audio_duration_s(num_samples: int, sample_rate: int) -> float:
    if sample_rate <= 0 or num_samples <= 0:
        return 0.0
    return float(num_samples) / float(sample_rate)


def enforce_duration(duration_s: float, *, max_s: float = MAX_DURATION_S) -> None:
    if duration_s > max_s:
        raise UploadTooLarge(f"audio too long ({duration_s:.1f}s > {max_s:.1f}s)")


@dataclass
class AsrMetrics:
    ready: bool = False
    model_id: str = ""
    waiting: int = 0
    in_flight: int = 0
    last_inference_ms: float | None = None
    inference_count: int = 0
    load_error: str | None = None
    cuda: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "model": self.model_id,
            "cuda": self.cuda,
            "waiting": self.waiting,
            "in_flight": self.in_flight,
            "queue_depth": self.waiting + self.in_flight,
            "last_inference_ms": self.last_inference_ms,
            "inference_count": self.inference_count,
            "load_error": self.load_error,
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "max_duration_s": MAX_DURATION_S,
        }
