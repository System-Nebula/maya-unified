"""SEC-001: loopback default and deployment profiles."""

from __future__ import annotations

import pytest

from services.deployment.profile import (
    default_host_for_profile,
    is_loopback_host,
    is_weak_session_secret,
    resolve_bind_host,
    resolve_maya_profile,
    should_mount_public_platform_routes,
    validate_startup_bind,
)


def test_default_profile_is_local() -> None:
    assert resolve_maya_profile({}) == "local"
    assert default_host_for_profile("local") == "127.0.0.1"
    assert resolve_bind_host(environ={}) == "127.0.0.1"


def test_operator_default_host_is_all_interfaces() -> None:
    assert resolve_bind_host(environ={"MAYA_PROFILE": "operator"}) == "0.0.0.0"


def test_local_non_loopback_fails_without_override() -> None:
    with pytest.raises(RuntimeError, match="refuses non-loopback"):
        validate_startup_bind(
            environ={"MAYA_PROFILE": "local", "HOST": "0.0.0.0"},
        )


def test_local_non_loopback_allowed_with_override_and_strong_secret() -> None:
    prof, host = validate_startup_bind(
        environ={
            "MAYA_PROFILE": "local",
            "HOST": "0.0.0.0",
            "MAYA_ALLOW_NON_LOOPBACK": "1",
            "SESSION_SECRET": "a-sufficiently-long-secret",
        }
    )
    assert prof == "local"
    assert host == "0.0.0.0"


def test_non_loopback_refuses_weak_secret() -> None:
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        validate_startup_bind(
            environ={
                "MAYA_PROFILE": "operator",
                "HOST": "0.0.0.0",
                "SESSION_SECRET": "dev-insecure-change-me",
            }
        )


def test_operator_loopback_refuses_weak_secret() -> None:
    # SEC-008: operator profile requires a strong secret on any bind.
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        validate_startup_bind(
            environ={
                "MAYA_PROFILE": "operator",
                "HOST": "127.0.0.1",
                "SESSION_SECRET": "dev-insecure-change-me",
            }
        )


def test_operator_loopback_allows_strong_secret() -> None:
    prof, host = validate_startup_bind(
        environ={
            "MAYA_PROFILE": "operator",
            "HOST": "127.0.0.1",
            "SESSION_SECRET": "a-sufficiently-long-secret",
        }
    )
    assert prof == "operator"
    assert host == "127.0.0.1"


def test_public_profile_refused() -> None:
    with pytest.raises(RuntimeError, match="public"):
        validate_startup_bind(environ={"MAYA_PROFILE": "public"})


def test_platform_routes_skipped_in_local() -> None:
    assert not should_mount_public_platform_routes("local")
    assert should_mount_public_platform_routes("operator")


def test_loopback_helpers() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")
    assert is_weak_session_secret("dev-insecure-change-me")
    assert is_weak_session_secret("short")
    assert not is_weak_session_secret("a-sufficiently-long-secret")
