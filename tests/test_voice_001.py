"""VOICE-001: atomic VoiceSessionController ownership."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from services.voice.audience import Audience
from services.voice.session_controller import SessionPhase, VoiceSessionController


def test_same_owner_start_is_idempotent() -> None:
    ctl = VoiceSessionController()
    owner = Audience.operator("op_a")
    first = ctl.begin_start(owner)
    assert first["ok"] and not first["idempotent"]
    second = ctl.begin_start(owner)
    assert second["ok"] and second["idempotent"]
    assert second["session_id"] == first["session_id"]
    done = ctl.complete_start(first["session_id"], first["generation_id"], ok=True)
    assert done["ok"]
    assert done["phase"] == SessionPhase.LISTENING.value


def test_different_owner_start_conflicts() -> None:
    ctl = VoiceSessionController()
    a = ctl.begin_start(Audience.operator("a"))
    assert a["ok"]
    ctl.complete_start(a["session_id"], a["generation_id"], ok=True)
    b = ctl.begin_start(Audience.operator("b"))
    assert not b["ok"]
    assert b["error"] == "conflict"
    assert b["owner"]["id"] == "a"


def test_non_owner_stop_forbidden_and_noop() -> None:
    ctl = VoiceSessionController()
    started = ctl.begin_start(Audience.operator("owner"))
    ctl.complete_start(started["session_id"], started["generation_id"], ok=True)
    denied = ctl.begin_stop(Audience.operator("intruder"))
    assert not denied["ok"]
    assert denied["error"] == "forbidden"
    snap = ctl.snapshot()
    assert snap is not None
    assert snap.session_id == started["session_id"]
    assert snap.phase is SessionPhase.LISTENING


def test_owner_stop_then_clear() -> None:
    ctl = VoiceSessionController()
    started = ctl.begin_start(Audience.operator("owner"))
    ctl.complete_start(started["session_id"], started["generation_id"], ok=True)
    stop = ctl.begin_stop(Audience.operator("owner"))
    assert stop["ok"]
    assert stop["cancel"].is_set()
    assert ctl.snapshot().phase is SessionPhase.STOPPING
    assert ctl.complete_stop(stop["session_id"])["cleared"]
    assert ctl.snapshot() is None


def test_start_while_stopping_rejected() -> None:
    ctl = VoiceSessionController()
    started = ctl.begin_start(Audience.operator("owner"))
    ctl.complete_start(started["session_id"], started["generation_id"], ok=True)
    ctl.begin_stop(Audience.operator("owner"))
    again = ctl.begin_start(Audience.operator("owner"))
    assert not again["ok"]
    assert again["error"] == "stopping"
    ctl.complete_stop(started["session_id"])
    ok = ctl.begin_start(Audience.operator("owner"))
    assert ok["ok"] and not ok["idempotent"]


def test_failed_start_compare_and_clears() -> None:
    ctl = VoiceSessionController()
    started = ctl.begin_start(Audience.operator("owner"))
    assert ctl.complete_start(started["session_id"], started["generation_id"], ok=False)
    assert ctl.snapshot() is None


def test_stale_complete_start_ignored() -> None:
    ctl = VoiceSessionController()
    first = ctl.begin_start(Audience.operator("owner"))
    # Simulate supersession via stop+new start after clear
    stop = ctl.begin_stop(Audience.operator("owner"), admin=True)
    ctl.complete_stop(stop["session_id"])
    second = ctl.begin_start(Audience.operator("owner"))
    stale = ctl.complete_start(first["session_id"], first["generation_id"], ok=True)
    assert not stale["ok"]
    assert ctl.snapshot().session_id == second["session_id"]


def test_is_current_false_after_stop() -> None:
    ctl = VoiceSessionController()
    started = ctl.begin_start(Audience.operator("owner"))
    sid, gen = started["session_id"], started["generation_id"]
    ctl.complete_start(sid, gen, ok=True)
    assert ctl.is_current(sid, gen)
    ctl.begin_stop(Audience.operator("owner"))
    assert not ctl.is_current(sid, gen)


def test_concurrent_starts_single_owner() -> None:
    ctl = VoiceSessionController()
    owner = Audience.operator("op")
    results: list[dict] = []

    def _start() -> None:
        results.append(ctl.begin_start(owner))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_start) for _ in range(8)]
        for f in futs:
            f.result()
    news = [r for r in results if r.get("ok") and not r.get("idempotent")]
    idem = [r for r in results if r.get("ok") and r.get("idempotent")]
    assert len(news) == 1
    assert len(idem) == 7
    assert all(r["session_id"] == news[0]["session_id"] for r in idem)
