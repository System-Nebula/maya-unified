"""CTX-001: turn-wide scheduler serializes operator context + turn work."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from services.voice.turn_scheduler import TURN_SCHEDULER, TurnScheduler


def test_hold_records_queue_and_hold_metrics() -> None:
    sched = TurnScheduler()
    with sched.hold(label="t", operator_id="op") as meta:
        time.sleep(0.01)
        assert meta.queue_wait_ms >= 0
        assert meta.label == "t"
    m = sched.metrics()
    assert m["turns"] == 1
    assert m["hold_ms_total"] >= 5


def test_concurrent_holds_are_serialized() -> None:
    sched = TurnScheduler()
    active = 0
    max_active = 0
    lock = threading.Lock()

    def _work() -> None:
        nonlocal active, max_active
        with sched.hold(label="c"):
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: _work(), range(4)))
    assert max_active == 1
    assert sched.metrics()["turns"] == 4


def test_process_scheduler_is_singleton_lock() -> None:
    """Two overlapping holds on TURN_SCHEDULER cannot both be inside at once."""
    seen: list[str] = []
    barrier = threading.Barrier(2)

    def a() -> None:
        with TURN_SCHEDULER.hold(label="a"):
            seen.append("a-in")
            barrier.wait(timeout=2)
            time.sleep(0.02)
            seen.append("a-out")

    def b() -> None:
        barrier.wait(timeout=2)
        with TURN_SCHEDULER.hold(label="b"):
            seen.append("b-in")
            seen.append("b-out")

    t1 = threading.Thread(target=a)
    t2 = threading.Thread(target=b)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    # a must fully exit before b enters
    assert seen.index("a-out") < seen.index("b-in")
