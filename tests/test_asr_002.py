"""ASR-002: timeouts, circuit breaker, Whisper fallback."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import numpy as np
import pytest

from stt import (
    CircuitBreaker,
    PermanentASRError,
    Qwen3ASRST,
    ResilientSTT,
    TransientASRError,
    _httpx_timeout,
    create_stt,
)


def _cfg(**kwargs):
    base = dict(
        backend="qwen3-asr",
        asr_base_url="http://127.0.0.1:8091/v1",
        asr_model="Qwen/Qwen3-ASR-0.6B",
        language="en",
        sample_rate=16000,
        whisper_model="tiny.en",
        whisper_compute_type="int8",
        device="cpu",
        asr_connect_timeout_s=1.0,
        asr_read_timeout_s=15.0,
        asr_write_timeout_s=5.0,
        asr_pool_timeout_s=1.0,
        asr_max_retries=1,
        asr_circuit_failures=2,
        asr_circuit_cooldown_s=30.0,
        asr_fallback_whisper=True,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_httpx_timeout_is_split() -> None:
    t = _httpx_timeout(_cfg())
    assert isinstance(t, httpx.Timeout)
    assert t.connect == 1.0
    assert t.read == 15.0
    assert t.write == 5.0
    assert t.pool == 1.0


def test_circuit_breaker_opens_and_cools_down() -> None:
    br = CircuitBreaker(max_failures=2, cooldown_s=10.0)
    assert br.allow(100.0)
    br.record_failure(100.0)
    assert br.allow(100.0)
    br.record_failure(100.0)
    assert br.is_open(100.0)
    assert not br.allow(105.0)
    assert br.allow(111.0)


def test_qwen_client_uses_explicit_timeout(monkeypatch) -> None:
    created = {}

    class FakeClient:
        def __init__(self, timeout=None):
            created["timeout"] = timeout

        def close(self):
            created["closed"] = True

    monkeypatch.setattr("httpx.Client", FakeClient)
    monkeypatch.setattr("stt.probe_qwen3_asr", lambda *_a, **_k: {"ok": True})
    client = Qwen3ASRST(_cfg(), probe=True)
    assert created["timeout"].read == 15.0
    client.close()
    assert created.get("closed") is True


def test_transient_retries_once(monkeypatch) -> None:
    monkeypatch.setattr("stt.probe_qwen3_asr", lambda *_a, **_k: {"ok": True})
    stt = Qwen3ASRST(_cfg(asr_max_retries=1), probe=False)
    calls = {"n": 0}

    def boom_then_ok(wav_bytes, *, filename):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientASRError("timeout")
        return "hello"

    monkeypatch.setattr(stt, "_post_once", boom_then_ok)
    assert stt.transcribe_bytes(b"RIFF") == "hello"
    assert calls["n"] == 2


def test_permanent_error_not_retried(monkeypatch) -> None:
    stt = Qwen3ASRST(_cfg(asr_max_retries=3), probe=False)
    calls = {"n": 0}

    def always_bad(wav_bytes, *, filename):
        calls["n"] += 1
        raise PermanentASRError("bad audio")

    monkeypatch.setattr(stt, "_post_once", always_bad)
    with pytest.raises(PermanentASRError):
        stt.transcribe_bytes(b"x")
    assert calls["n"] == 1


def test_resilient_falls_back_on_transient(monkeypatch) -> None:
    primary = MagicMock()
    primary.transcribe_array.side_effect = TransientASRError("down")
    fallback = MagicMock()
    fallback.transcribe_array.return_value = "from-whisper"
    resilient = ResilientSTT(
        cfg=_cfg(asr_circuit_failures=3),
        primary=primary,
        fallback=fallback,
    )
    audio = np.zeros(1600, dtype=np.int16)
    assert resilient.transcribe_array(audio) == "from-whisper"
    assert resilient.degraded is True
    assert resilient.status()["degraded"] is True


def test_resilient_does_not_fallback_on_permanent() -> None:
    primary = MagicMock()
    primary.transcribe_array.side_effect = PermanentASRError("invalid")
    fallback = MagicMock()
    resilient = ResilientSTT(cfg=_cfg(), primary=primary, fallback=fallback)
    with pytest.raises(PermanentASRError):
        resilient.transcribe_array(np.zeros(100, dtype=np.int16))
    fallback.transcribe_array.assert_not_called()


def test_open_circuit_skips_primary() -> None:
    primary = MagicMock()
    fallback = MagicMock()
    fallback.transcribe_array.return_value = "fb"
    resilient = ResilientSTT(
        cfg=_cfg(asr_circuit_failures=1, asr_circuit_cooldown_s=60),
        primary=primary,
        fallback=fallback,
    )
    resilient.breaker.record_failure()
    assert resilient.breaker.is_open()
    assert resilient.transcribe_array(np.zeros(10, dtype=np.int16)) == "fb"
    primary.transcribe_array.assert_not_called()


def test_create_stt_qwen_down_uses_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "stt.probe_qwen3_asr",
        lambda *_a, **_k: {"ok": False, "detail": "down — start-asr"},
    )
    # Avoid loading real Whisper.
    fake = MagicMock()
    fake.status.return_value = {"backend": "whisper", "degraded": False}
    monkeypatch.setattr("stt.LazyWhisperSTT", lambda cfg: fake)
    stt = create_stt(_cfg(asr_fallback_whisper=True), probe_qwen=True)
    assert isinstance(stt, ResilientSTT)
    assert stt.status()["degraded"] is True
    assert stt.primary is None
