"""Tests for operator profile seed script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_seed_operator_profile_dry_run() -> None:
    script = ROOT / "scripts" / "seed_operator_profile.py"
    result = subprocess.run(
        [sys.executable, str(script), "--profile", "example", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "misskatie" in result.stdout
    assert "ukf" in result.stdout
    assert "dry-run" in result.stdout
