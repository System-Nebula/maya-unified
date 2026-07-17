"""TEST-002: documented security and audience regression suite modules."""

from __future__ import annotations

from pathlib import Path

# (category, path relative to maya-unified root)
REQUIRED_SECURITY_MODULES: tuple[tuple[str, str], ...] = (
    ("deployment_profile", "tests/test_sec_001.py"),
    ("route_authorization", "tests/security/test_api_auth_matrix.py"),
    ("command_capability", "tests/test_sec_003.py"),
    ("cross_operator_sse", "tests/test_event_audience.py"),
    ("room_guest_audience", "tests/test_voice_event_isolation.py"),
    ("webllm_ownership", "tests/test_sec_005.py"),
    ("settings_redaction", "tests/test_sec_006.py"),
    ("webhook_mailgun", "tests/test_sec_007.py"),
    ("bootstrap_session", "tests/test_sec_008.py"),
    ("discord_shim", "tests/test_sec_009.py"),
)

SUITE_ROOT = Path(__file__).resolve().parents[2]


def required_paths() -> list[Path]:
    return [SUITE_ROOT / rel for _, rel in REQUIRED_SECURITY_MODULES]


def suite_pytest_args() -> list[str]:
    """Args for ``python -m pytest`` to run the full TEST-002 suite."""
    return [str(p) for p in required_paths()]
