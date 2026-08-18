"""OpenBao KV lookup for slskd credentials (env still wins)."""

from __future__ import annotations

import json
from unittest.mock import patch

from services.secrets.openbao import (
    SLSKD_SECRET_PATH,
    bao_addr,
    bao_is_local,
    export_slskd_shell,
    read_secret,
    seed_slskd_from_env,
    slskd_credentials,
    write_secret,
)


class _FakeResponse:
    def __init__(self, payload: dict | None, *, status: int = 200) -> None:
        self._payload = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.status = status

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_empty_bao_addr_uses_localhost(monkeypatch) -> None:
    monkeypatch.setenv("BAO_ADDR", "")
    monkeypatch.setenv("VAULT_ADDR", "")
    assert bao_addr() == "http://127.0.0.1:8200"
    assert bao_is_local()


def test_remote_bao_addr_is_not_local(monkeypatch) -> None:
    monkeypatch.setenv("BAO_ADDR", "https://openbao.example.internal:8200")
    assert not bao_is_local()


def test_read_secret_unwraps_kv_v2(monkeypatch) -> None:
    monkeypatch.setenv("BAO_ADDR", "http://127.0.0.1:8200")
    monkeypatch.setenv("BAO_TOKEN", "dev-token")

    def fake_urlopen(request, timeout=3.0):
        assert request.full_url.endswith("/v1/secret/data/maya/integrations/slskd")
        assert request.get_method() == "GET"
        return _FakeResponse(
            {"data": {"data": {"username": "slsk-user", "password": "slsk-pass"}}}
        )

    with patch("services.secrets.openbao.urllib.request.urlopen", fake_urlopen):
        secret = read_secret(SLSKD_SECRET_PATH)
    assert secret["username"] == "slsk-user"
    assert secret["password"] == "slsk-pass"


def test_write_secret_posts_kv_v2(monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    captured: dict = {}

    def fake_urlopen(request, timeout=5.0):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"data": {"version": 1}})

    with patch("services.secrets.openbao.urllib.request.urlopen", fake_urlopen):
        write_secret(SLSKD_SECRET_PATH, {"username": "u", "password": "p"})
    assert captured["url"].endswith("/v1/secret/data/maya/integrations/slskd")
    assert captured["method"] == "POST"
    assert captured["body"] == {"data": {"username": "u", "password": "p"}}


def test_seed_from_env_skips_when_kv_present(monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    monkeypatch.setenv("SLSKD_SLSK_USERNAME", "env-user")
    monkeypatch.setenv("SLSKD_SLSK_PASSWORD", "env-pass")
    with patch(
        "services.secrets.openbao.slskd_credentials",
        return_value={"username": "bao-user", "password": "bao-pass", "api_key": ""},
    ):
        with patch("services.secrets.openbao.write_secret") as write:
            status = seed_slskd_from_env()
    assert "already present" in status
    write.assert_not_called()


def test_seed_from_env_writes_when_kv_empty(monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    monkeypatch.setenv("SLSKD_SLSK_USERNAME", "env-user")
    monkeypatch.setenv("SLSKD_SLSK_PASSWORD", "env-pass")
    monkeypatch.delenv("SLSKD_API_KEY", raising=False)
    with patch(
        "services.secrets.openbao.slskd_credentials",
        return_value={"username": "", "password": "", "api_key": ""},
    ):
        with patch("services.secrets.openbao.write_secret") as write:
            status = seed_slskd_from_env()
    assert status.startswith("seeded")
    write.assert_called_once_with(
        SLSKD_SECRET_PATH, {"username": "env-user", "password": "env-pass"}
    )


def test_slskd_credentials_and_shell_export(monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    monkeypatch.delenv("SLSKD_SLSK_USERNAME", raising=False)
    monkeypatch.delenv("SLSKD_SLSK_PASSWORD", raising=False)

    with patch(
        "services.secrets.openbao.read_secret",
        return_value={"username": "u", "password": "p w"},
    ):
        creds = slskd_credentials()
        shell = export_slskd_shell()
    assert creds["username"] == "u"
    assert "export SLSKD_SLSK_USERNAME=u" in shell
    assert "export SLSKD_SLSK_PASSWORD='p w'" in shell or 'SLSKD_SLSK_PASSWORD="p w"' in shell


def test_env_overrides_openbao_export(monkeypatch) -> None:
    monkeypatch.setenv("SLSKD_SLSK_USERNAME", "from-env")
    monkeypatch.setenv("SLSKD_SLSK_PASSWORD", "from-env-pw")
    with patch(
        "services.secrets.openbao.read_secret",
        return_value={"username": "from-bao", "password": "from-bao-pw"},
    ):
        assert export_slskd_shell() == ""


def test_missing_token_skips_seed(monkeypatch) -> None:
    monkeypatch.delenv("BAO_TOKEN", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    assert "token missing" in seed_slskd_from_env()
