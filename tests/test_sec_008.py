"""SEC-008: bootstrap credentials and session security."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.auth.login_throttle import (
    check_login_allowed,
    record_login_failure,
    reset_login_throttle_for_tests,
)
from services.auth.seed import seed_default_operator_enabled
from services.auth.session import (
    ensure_local_session_secret,
    sign_operator_session,
    verify_operator_session,
)
from services.auth.session_version import (
    bump_session_version,
    get_session_version,
    reset_session_versions_for_tests,
)
from services.deployment.profile import validate_startup_bind


@pytest.fixture(autouse=True)
def _reset_auth_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VA_DATA_DIR", str(tmp_path))
    # Keep DATA_DIR resolution consistent for session secret / versions.
    monkeypatch.setattr("services.paths.DATA_DIR", Path(tmp_path))
    monkeypatch.setattr("services.auth.session.DATA_DIR", Path(tmp_path))
    monkeypatch.setattr("services.auth.session_version.DATA_DIR", Path(tmp_path))
    reset_session_versions_for_tests()
    reset_login_throttle_for_tests()
    yield
    reset_session_versions_for_tests()
    reset_login_throttle_for_tests()


def test_default_seed_disabled() -> None:
    assert seed_default_operator_enabled({}) is False
    assert seed_default_operator_enabled({"MAYA_SEED_DEFAULT_OPERATOR": "1"}) is True


def test_operator_profile_weak_secret_blocks_startup() -> None:
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        validate_startup_bind(
            environ={
                "MAYA_PROFILE": "operator",
                "HOST": "127.0.0.1",
                "SESSION_SECRET": "dev-insecure-change-me",
            }
        )


def test_local_loopback_generates_session_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("services.auth.session.DATA_DIR", Path(tmp_path))
    env = {"MAYA_PROFILE": "local", "HOST": "127.0.0.1"}
    secret = ensure_local_session_secret(environ=env)
    assert len(secret) >= 16
    assert env["SESSION_SECRET"] == secret
    path = Path(tmp_path) / "session_secret"
    assert path.is_file()
    # Second call reuses file
    again = ensure_local_session_secret(environ={"MAYA_PROFILE": "local"})
    assert again == secret


def test_password_change_invalidates_old_session(monkeypatch) -> None:
    monkeypatch.setenv("SESSION_SECRET", "a-sufficiently-long-secret")
    oid = "op-1"
    token = sign_operator_session(oid)
    assert verify_operator_session(token) is not None
    bump_session_version(oid)
    assert verify_operator_session(token) is None
    fresh = sign_operator_session(oid)
    assert verify_operator_session(fresh) is not None
    assert get_session_version(oid) == 1


def test_login_rate_limit_uniform() -> None:
    for _ in range(8):
        assert check_login_allowed("1.2.3.4", "anyone")
        record_login_failure("1.2.3.4", "anyone")
    assert check_login_allowed("1.2.3.4", "anyone") is False
    # Different username still limited by same IP+username key only
    assert check_login_allowed("1.2.3.4", "other") is True
