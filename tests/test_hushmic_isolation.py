"""AUDIO-003: namespaced HushMic keys, single-pass, bounded enhancer map."""

from __future__ import annotations

import numpy as np

from services.voice.hushmic import (
    HushMicProcessor,
    browser_key,
    discord_key,
    downsample_mono_48k_to_16k_int16,
)


class _SpyEnhancer:
    def __init__(self) -> None:
        self.process_calls = 0
        self.reset_calls = 0
        self.samples_seen = 0
        self.closed = False

    def process(self, samples, sample_rate=48000):  # noqa: ANN001, ARG002
        self.process_calls += 1
        self.samples_seen += int(getattr(samples, "size", len(samples)))
        return samples

    def reset(self) -> None:
        self.reset_calls += 1

    def close(self) -> None:
        self.closed = True


def _pcm(samples: int = 480, value: int = 1000) -> bytes:
    return np.full(samples, value, dtype="<i2").tobytes()


def test_browser_reconnect_does_not_reset_discord() -> None:
    spies: list[_SpyEnhancer] = []

    def factory() -> _SpyEnhancer:
        spy = _SpyEnhancer()
        spies.append(spy)
        return spy

    proc = HushMicProcessor(enabled=True, enhancer_factory=factory, max_enhancers=8)
    bkey = browser_key("sess-a")
    dkey = discord_key(42, guild_id=7)

    proc.process_mono_48k(_pcm(), key=bkey)
    proc.process_mono_48k(_pcm(), key=dkey)
    assert proc.enhancer_count() == 2

    discord_spy = spies[1]
    assert discord_spy.process_calls == 1

    # Browser reconnect resets only the browser key.
    proc.reset(bkey)
    assert spies[0].reset_calls == 1
    assert discord_spy.reset_calls == 0

    # reset(None) must not wipe Discord.
    proc.reset(None)
    assert discord_spy.reset_calls == 0
    assert proc.has_key(dkey)


def test_single_pass_spy_per_sample_via_stream_then_downsample() -> None:
    """Stream enhance once; finalize path only resamples (no second enhance)."""
    spies: list[_SpyEnhancer] = []

    def factory() -> _SpyEnhancer:
        spy = _SpyEnhancer()
        spies.append(spy)
        return spy

    proc = HushMicProcessor(enabled=True, enhancer_factory=factory)
    key = browser_key("turn-1")
    chunk_a = _pcm(480)
    chunk_b = _pcm(480, value=2000)
    out_a = proc.process_mono_48k(chunk_a, key=key)
    out_b = proc.process_mono_48k(chunk_b, key=key)
    enhanced = out_a + out_b
    assert spies[0].process_calls == 2
    assert spies[0].samples_seen == 960

    # Finalize: downsample only — must not call process again.
    before = spies[0].process_calls
    _ = downsample_mono_48k_to_16k_int16(enhanced)
    assert spies[0].process_calls == before


def test_enhancer_dictionary_remains_bounded() -> None:
    spies: list[_SpyEnhancer] = []

    def factory() -> _SpyEnhancer:
        spy = _SpyEnhancer()
        spies.append(spy)
        return spy

    proc = HushMicProcessor(
        enabled=True,
        enhancer_factory=factory,
        max_enhancers=3,
        ttl_s=3600,
    )
    for i in range(10):
        proc.process_mono_48k(_pcm(), key=browser_key(f"s-{i}"))
    assert proc.enhancer_count() <= 3
    assert proc.status()["evictions"] >= 7


def test_browser_and_discord_keys_do_not_collide_on_zero() -> None:
    spies: list[_SpyEnhancer] = []

    def factory() -> _SpyEnhancer:
        spy = _SpyEnhancer()
        spies.append(spy)
        return spy

    proc = HushMicProcessor(enabled=True, enhancer_factory=factory)
    proc.process_mono_48k(_pcm(), key=browser_key("default"))
    # Discord user_id 0 must not share the browser enhancer.
    proc.process_mono_48k(_pcm(), key=discord_key(0, guild_id=1))
    assert proc.enhancer_count() == 2
    assert spies[0] is not spies[1]


def test_ttl_evicts_stale_keys(monkeypatch) -> None:
    clock = {"t": 1000.0}

    def mono() -> float:
        return clock["t"]

    monkeypatch.setattr("services.voice.hushmic.time.monotonic", mono)
    proc = HushMicProcessor(
        enabled=True,
        enhancer_factory=_SpyEnhancer,
        max_enhancers=8,
        ttl_s=10.0,
    )
    proc.process_mono_48k(_pcm(), key=browser_key("old"))
    clock["t"] = 1020.0
    proc.process_mono_48k(_pcm(), key=browser_key("new"))
    assert not proc.has_key(browser_key("old"))
    assert proc.has_key(browser_key("new"))


def test_browser_replacement_connection_gets_isolated_enhancer_key() -> None:
    first = browser_key("session-a", connection_id="connection-1")
    replacement = browser_key("session-a", connection_id="connection-2")

    assert first != replacement
    assert first[:2] == replacement[:2] == ("browser", "session-a")
    assert browser_key("session-a") == ("browser", "session-a")
