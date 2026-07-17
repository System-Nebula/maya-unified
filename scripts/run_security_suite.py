#!/usr/bin/env python3
"""Run the TEST-002 security / audience regression suite.

Usage (from maya-unified)::

    uv run --extra dev python scripts/run_security_suite.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages" / "voice-runtime"))
sys.path.insert(0, str(ROOT / "apps" / "maya-gateway" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "discord-shim" / "src"))

from tests.security.suite_manifest import suite_pytest_args  # noqa: E402


def main() -> int:
    import pytest

    args = [
        "-q",
        "tests/security/test_regression_suite.py",
        *suite_pytest_args(),
    ]
    return int(pytest.main(args))


if __name__ == "__main__":
    raise SystemExit(main())
