"""Adaptive VC end-of-utterance silence."""

from __future__ import annotations

import time

from tools.discord_vc_listen import _UserBuf, build_utterance_sink


def test_effective_silence_grows_with_spoken_duration() -> None:
    sink = build_utterance_sink(
        on_utterance=lambda _p: None,
        silence_ms=1800,
        merge_ms=1500,
        bot_speaking_fn=lambda: False,
    )
    try:
        now = time.monotonic()
        short = _UserBuf(chunks=[b"x"], last_write_at=now, started_at=now - 0.5)
        long = _UserBuf(chunks=[b"x"], last_write_at=now, started_at=now - 4.0)
        short_need = sink._effective_silence_sec(short)
        long_need = sink._effective_silence_sec(long)
        assert short_need >= 1.8
        assert long_need > short_need
        assert long_need <= 3.2
    finally:
        sink.cleanup()
