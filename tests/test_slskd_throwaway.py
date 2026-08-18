"""Throwaway Soulseek account allocation (first login creates the user)."""

from __future__ import annotations

from unittest.mock import patch

from services.secrets.openbao import (
    EXAMPLE_SLSKD_USERNAME,
    THROWAWAY_USERNAME_PREFIX,
    allocate_throwaway_slskd,
    new_throwaway_username,
)


def test_throwaway_username_shape() -> None:
    name = new_throwaway_username()
    assert name.startswith(THROWAWAY_USERNAME_PREFIX)
    assert len(name) == len(THROWAWAY_USERNAME_PREFIX) + 8
    assert name[len(THROWAWAY_USERNAME_PREFIX) :].isalnum()


def test_allocate_reuses_non_example_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("services.secrets.openbao.DEV_SEED_LOCAL", tmp_path / "dev-seed.json")
    monkeypatch.delenv("SLSKD_EXAMPLE", raising=False)
    with patch(
        "services.secrets.openbao.slskd_credentials",
        return_value={
            "username": "kept-user",
            "password": "kept-pass",
            "api_key": "",
            "network": "soulseek",
            "throwaway": "",
        },
    ):
        with patch("services.secrets.openbao.persist_slskd_secret") as persist:
            status = allocate_throwaway_slskd()
    assert "reusing existing" in status
    persist.assert_not_called()


def test_allocate_reuses_throwaway(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("services.secrets.openbao.DEV_SEED_LOCAL", tmp_path / "dev-seed.json")
    monkeypatch.delenv("SLSKD_EXAMPLE", raising=False)
    with patch(
        "services.secrets.openbao.slskd_credentials",
        return_value={
            "username": "MayaDevabcd1234",
            "password": "secret",
            "api_key": "ci-cloud-agent-slskd-key",
            "network": "soulseek",
            "throwaway": "true",
        },
    ):
        with patch("services.secrets.openbao.persist_slskd_secret") as persist:
            status = allocate_throwaway_slskd()
    assert "reusing throwaway" in status
    persist.assert_not_called()


def test_allocate_replaces_example_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("services.secrets.openbao.DEV_SEED_LOCAL", tmp_path / "dev-seed.json")
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    monkeypatch.delenv("SLSKD_EXAMPLE", raising=False)
    monkeypatch.delenv("SLSKD_SLSK_USERNAME", raising=False)
    captured: dict = {}

    def fake_persist(data: dict) -> None:
        captured.update(data)

    with patch(
        "services.secrets.openbao.slskd_credentials",
        return_value={
            "username": EXAMPLE_SLSKD_USERNAME,
            "password": "maya-dev-example",
            "api_key": "ci-cloud-agent-slskd-key",
            "network": "example",
            "throwaway": "",
        },
    ):
        with patch("services.secrets.openbao.persist_slskd_secret", side_effect=fake_persist):
            status = allocate_throwaway_slskd()
    assert status.startswith("allocated")
    assert captured["username"].startswith(THROWAWAY_USERNAME_PREFIX)
    assert captured["username"] != EXAMPLE_SLSKD_USERNAME
    assert captured["network"] == "soulseek"
    assert captured["throwaway"] is True
    assert len(captured["password"]) >= 16
    assert SLSKD_SECRET_PATH


def test_allocate_force_replaces(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("services.secrets.openbao.DEV_SEED_LOCAL", tmp_path / "dev-seed.json")
    monkeypatch.delenv("SLSKD_EXAMPLE", raising=False)
    with patch(
        "services.secrets.openbao.slskd_credentials",
        return_value={
            "username": "MayaDev11111111",
            "password": "old",
            "api_key": "ci-cloud-agent-slskd-key",
            "network": "soulseek",
            "throwaway": "true",
        },
    ):
        with patch("services.secrets.openbao.persist_slskd_secret") as persist:
            status = allocate_throwaway_slskd(force=True)
    assert status.startswith("allocated")
    persist.assert_called_once()
    assert persist.call_args[0][0]["username"] != "MayaDev11111111"
