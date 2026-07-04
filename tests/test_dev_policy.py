"""Tests for dev dependency policy."""

from __future__ import annotations

from services.discovery.policy import (
    DEV_POLICY_MESSAGE,
    apply_dev_policy,
    comfy_satisfies_dev_policy,
    dev_policy_blocks_imagine,
    imagine_capability_ready,
    is_dev,
)


def test_is_dev(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert is_dev() is True

    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert is_dev() is False


def test_dev_policy_blocks_without_comfy(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("MAYA_FAKE_COMFY", raising=False)
    health = {"status": "error", "detail": "down"}
    assert dev_policy_blocks_imagine(health) is True
    assert comfy_satisfies_dev_policy(health) is False


def test_dev_policy_allows_fake_comfy(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("MAYA_FAKE_COMFY", "1")
    health = {"status": "error", "detail": "down"}
    assert dev_policy_blocks_imagine(health) is False
    assert comfy_satisfies_dev_policy(health) is True


def test_prod_does_not_block_on_error(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    health = {"status": "error", "detail": "down"}
    assert dev_policy_blocks_imagine(health) is False


def test_apply_dev_policy_sets_imagine_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("MAYA_FAKE_COMFY", raising=False)
    apply_dev_policy({"comfyui": {"status": "error", "detail": "down"}})
    settings = {"imagine": {"enabled": True}}
    assert imagine_capability_ready({"status": "error"}, settings=settings) is False


def test_imagine_capability_ready_legacy_discord() -> None:
    settings = {"discord": {"imagine_enabled": True}}
    assert imagine_capability_ready({"status": "ok"}, settings=settings) is True


def test_imagine_capability_ready_ok_from_cached_status_poll(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("MAYA_FAKE_COMFY", raising=False)
    settings = {"imagine": {"enabled": True}}
    cached_ok = {"status": "ok", "detail": "comfyui-api reachable at http://127.0.0.1:3030"}
    assert imagine_capability_ready(cached_ok, settings=settings) is True


def test_imagine_capability_ready_false_for_skipped_only(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("MAYA_FAKE_COMFY", raising=False)
    settings = {"imagine": {"enabled": True}}
    assert imagine_capability_ready({"status": "skipped", "detail": "Probe skipped"}, settings=settings) is False


def test_dev_policy_message_constant() -> None:
    assert "MAYA_FAKE_COMFY" in DEV_POLICY_MESSAGE
