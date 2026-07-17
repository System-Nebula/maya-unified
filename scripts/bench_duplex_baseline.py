#!/usr/bin/env python3
"""PRE-001 duplex baseline harness.

Documented command (CPU-safe stub — no GPU/ASR required):

    uv run python scripts/bench_duplex_baseline.py --mode stub --warmup 1 --reps 10 \\
      --out artifacts/baseline_results.json \\
      --machine-out artifacts/baseline_machine.json

Live mode is reserved for consented speech fixtures once OBS timing hooks land.
Do not use random noise. Do not embed LAN hosts or model IDs in the schema.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.voice.baseline_machine import collect_machine_metadata  # noqa: E402
from services.voice.baseline_schema import (  # noqa: E402
    SCHEMA_VERSION,
    BaselineCounters,
    BaselineInput,
    BaselineSample,
)
from services.voice.baseline_stats import aggregate_samples  # noqa: E402


def _stub_sample(*, cold: bool, index: int) -> BaselineSample:
    """Deterministic synthetic timings (warm turns faster than cold)."""
    base = 40.0 if cold else 18.0
    jitter = float((index % 5) * 1.5)
    speech_end_to_finalized = base + 5.0 + jitter
    asr = base + 30.0 + jitter
    llm_first = base + 80.0 + jitter * 2
    tts_req = 8.0 + jitter * 0.2
    first_pcm = 25.0 + jitter
    return BaselineSample(
        cold=cold,
        speech_end_to_finalized_ms=speech_end_to_finalized,
        asr_duration_ms=asr,
        transcript_to_llm_first_token_ms=llm_first,
        llm_first_token_to_tts_request_ms=tts_req,
        tts_request_to_first_pcm_ms=first_pcm,
        speech_end_to_first_audible_pcm_ms=speech_end_to_finalized + asr + llm_first + tts_req + first_pcm,
        barge_onset_to_duck_ms=12.0 + jitter * 0.1,
        barge_confirm_to_silence_ms=40.0 + jitter,
        event_loop_lag_ms=1.0 + (0.2 if not cold else 1.5),
        underruns=0,
        dropped_mic_frames=0 if not cold else 1,
        ws_reconnects=0,
        queue_high_water={"utterance": 1 + (2 if cold else 0)},
    )


def run_stub(*, warmup: int, reps: int) -> tuple[list[BaselineSample], BaselineCounters]:
    samples: list[BaselineSample] = []
    # One cold sample first (warmup discard still tagged cold for aggregates).
    cold = _stub_sample(cold=True, index=0)
    samples.append(cold)
    for i in range(max(0, warmup - 1)):
        samples.append(_stub_sample(cold=True, index=i + 1))
    for i in range(reps):
        samples.append(_stub_sample(cold=False, index=i))

    measured = samples[warmup:] if warmup > 0 else samples
    counters = BaselineCounters()
    for s in measured:
        counters.underruns += s.underruns
        counters.dropped_mic_frames += s.dropped_mic_frames
        counters.ws_reconnects += s.ws_reconnects
        if s.event_loop_lag_ms is not None:
            counters.event_loop_lag_ms_max = max(
                counters.event_loop_lag_ms_max, float(s.event_loop_lag_ms)
            )
        for k, v in (s.queue_high_water or {}).items():
            counters.queue_high_water[k] = max(counters.queue_high_water.get(k, 0), int(v))
    return samples, counters


def build_results(
    *,
    mode: str,
    warmup: int,
    reps: int,
    samples: list[BaselineSample],
    counters: BaselineCounters,
) -> dict:
    measured = samples[warmup:] if warmup > 0 else list(samples)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "input": BaselineInput(fixture="stub" if mode == "stub" else "live").to_dict(),
        "warmup_discarded": warmup,
        "reps": reps,
        "samples": [s.to_dict() for s in measured],
        "aggregates": aggregate_samples(measured),
        "counters": counters.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maya duplex baseline (PRE-001)")
    parser.add_argument("--mode", choices=("stub", "live"), default="stub")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--reps", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--machine-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.mode == "live":
        print(
            "live mode is not implemented yet — capture with stub until OBS timing hooks land",
            file=sys.stderr,
        )
        return 2

    samples, counters = run_stub(warmup=args.warmup, reps=args.reps)
    results = build_results(
        mode="stub",
        warmup=args.warmup,
        reps=args.reps,
        samples=samples,
        counters=counters,
    )
    machine = collect_machine_metadata()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.machine_out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    args.machine_out.write_text(json.dumps(machine, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"wrote {args.machine_out}")
    warm = results["aggregates"]["warm"].get("speech_end_to_first_audible_pcm_ms") or {}
    print(f"warm speech_end_to_first_audible_pcm_ms p50={warm.get('p50')} p95={warm.get('p95')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
