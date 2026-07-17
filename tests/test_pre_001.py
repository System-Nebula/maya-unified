"""PRE-001: duplex baseline stub harness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from services.voice.baseline_schema import BaselineSample
from services.voice.baseline_stats import aggregate_samples, compare_warm_p95, percentile

ROOT = Path(__file__).resolve().parents[1]


def test_percentile() -> None:
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([], 50) is None


def test_stub_baseline_cli(tmp_path: Path) -> None:
    out = tmp_path / "results.json"
    machine = tmp_path / "machine.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "bench_duplex_baseline.py"),
            "--mode",
            "stub",
            "--warmup",
            "1",
            "--reps",
            "5",
            "--out",
            str(out),
            "--machine-out",
            str(machine),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    results = json.loads(out.read_text(encoding="utf-8"))
    meta = json.loads(machine.read_text(encoding="utf-8"))
    assert results["schema_version"] == 1
    assert results["mode"] == "stub"
    assert results["input"]["sample_rate"] == 48000
    assert len(results["samples"]) == 5
    assert all(s["cold"] is False for s in results["samples"])
    warm = results["aggregates"]["warm"]["speech_end_to_first_audible_pcm_ms"]
    assert warm["p50"] is not None and warm["p95"] is not None
    assert "python" in meta
    assert "python" not in results


def test_warm_p95_regression_gate() -> None:
    samples = [
        BaselineSample(cold=False, speech_end_to_first_audible_pcm_ms=100.0),
        BaselineSample(cold=False, speech_end_to_first_audible_pcm_ms=110.0),
        BaselineSample(cold=False, speech_end_to_first_audible_pcm_ms=120.0),
    ]
    base = aggregate_samples(samples)
    worse = aggregate_samples(
        [
            BaselineSample(cold=False, speech_end_to_first_audible_pcm_ms=200.0),
            BaselineSample(cold=False, speech_end_to_first_audible_pcm_ms=220.0),
        ]
    )
    ok, _msg = compare_warm_p95(
        base, worse, field="speech_end_to_first_audible_pcm_ms", max_regression_pct=20
    )
    assert ok is False
    ok2, _ = compare_warm_p95(
        base, base, field="speech_end_to_first_audible_pcm_ms", max_regression_pct=20
    )
    assert ok2 is True
