"""Aggregate p50/p95 helpers for PRE-001 duplex baselines."""

from __future__ import annotations

from typing import Iterable

from services.voice.baseline_schema import LATENCY_FIELDS, BaselineSample


def percentile(values: Iterable[float], pct: float) -> float | None:
    """Linear-interpolated percentile for ``pct`` in 0..100."""
    data = sorted(float(v) for v in values)
    if not data:
        return None
    if pct <= 0:
        return data[0]
    if pct >= 100:
        return data[-1]
    if len(data) == 1:
        return data[0]
    pos = (pct / 100.0) * (len(data) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    frac = pos - lo
    return data[lo] * (1.0 - frac) + data[hi] * frac


def aggregate_samples(samples: list[BaselineSample]) -> dict[str, dict[str, dict[str, float | None]]]:
    """Build cold/warm aggregates with p50/p95 per latency field."""
    out: dict[str, dict[str, dict[str, float | None]]] = {"cold": {}, "warm": {}}
    for phase, subset in (
        ("cold", [s for s in samples if s.cold]),
        ("warm", [s for s in samples if not s.cold]),
    ):
        for field in LATENCY_FIELDS:
            vals = [
                float(getattr(s, field))
                for s in subset
                if getattr(s, field) is not None
            ]
            out[phase][field] = {
                "p50": percentile(vals, 50),
                "p95": percentile(vals, 95),
                "n": float(len(vals)),
            }
    return out


def compare_warm_p95(
    baseline: dict[str, dict[str, dict[str, float | None]]],
    current: dict[str, dict[str, dict[str, float | None]]],
    *,
    field: str,
    max_regression_pct: float,
) -> tuple[bool, str]:
    """Return (ok, message). Fails when warm p95 rises more than ``max_regression_pct``."""
    base = (baseline.get("warm") or {}).get(field) or {}
    cur = (current.get("warm") or {}).get(field) or {}
    b = base.get("p95")
    c = cur.get("p95")
    if b is None or c is None or b <= 0:
        return True, "skipped (missing baseline or current p95)"
    limit = float(b) * (1.0 + float(max_regression_pct) / 100.0)
    if float(c) > limit:
        return False, f"{field} warm p95 {c:.2f} exceeds {limit:.2f} (+{max_regression_pct}% of {b:.2f})"
    return True, f"{field} warm p95 {c:.2f} within +{max_regression_pct}% of {b:.2f}"
