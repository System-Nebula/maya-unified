"""Turn-wide context scheduler (CTX-001).

Lock order (never invert; never hold a higher lock while acquiring a lower one
across await/I/O that can block other operators indefinitely without intent):

1. ``VoiceSessionController._lock`` — short compare-and-swap only; no I/O
2. ``TurnScheduler`` — full operator/room turn (context activate → persist)
3. ``INFERENCE_LOCK`` — shared LLM/GPU inference
4. Resource locks (``_tts_lock``, etc.)

Never acquire (1) while holding (2)/(3)/(4). Never await browser/network work
while holding (1). Holding (2) across LLM/TTS is intentional serialization for
one shared agent process.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class TurnHold:
    """Metadata for one acquired turn slot."""

    label: str
    operator_id: str | None
    queue_wait_ms: float
    started_monotonic: float = field(default_factory=time.monotonic)


@dataclass
class TurnScheduler:
    """Serializes operator context mutation + turn work for one shared agent."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _wait_ms_total: float = 0.0
    _hold_ms_total: float = 0.0
    _turns: int = 0
    _metrics_lock: threading.Lock = field(default_factory=threading.Lock)

    @contextmanager
    def hold(
        self,
        *,
        label: str = "turn",
        operator_id: str | None = None,
    ) -> Iterator[TurnHold]:
        t_wait0 = time.perf_counter()
        self._lock.acquire()
        queue_wait_ms = (time.perf_counter() - t_wait0) * 1000.0
        meta = TurnHold(
            label=label,
            operator_id=operator_id,
            queue_wait_ms=queue_wait_ms,
        )
        t_hold0 = time.perf_counter()
        try:
            yield meta
        finally:
            hold_ms = (time.perf_counter() - t_hold0) * 1000.0
            with self._metrics_lock:
                self._wait_ms_total += queue_wait_ms
                self._hold_ms_total += hold_ms
                self._turns += 1
            self._lock.release()

    def metrics(self) -> dict[str, float | int]:
        with self._metrics_lock:
            n = max(1, self._turns)
            return {
                "turns": self._turns,
                "queue_wait_ms_total": round(self._wait_ms_total, 3),
                "hold_ms_total": round(self._hold_ms_total, 3),
                "queue_wait_ms_avg": round(self._wait_ms_total / n, 3),
                "hold_ms_avg": round(self._hold_ms_total / n, 3),
            }

    def reset_metrics_for_tests(self) -> None:
        with self._metrics_lock:
            self._wait_ms_total = 0.0
            self._hold_ms_total = 0.0
            self._turns = 0


# Process-wide scheduler for the unified voice hub.
TURN_SCHEDULER = TurnScheduler()
