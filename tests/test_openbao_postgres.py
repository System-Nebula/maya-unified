"""OpenBao KV lookup for Postgres (env DATABASE_URL still wins)."""

from __future__ import annotations

import json
from unittest.mock import patch

from services.secrets.openbao import (
    POSTGRES_SECRET_PATH,
    apply_database_url_env,
    database_url,
    export_postgres_shell,
    postgres_secret,
    seed_postgres_from_env,
)


def test_postgres_secret_composes_url(monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MAYA_DATABASE_URL", raising=False)
    with patch(
        "services.secrets.openbao.read_secret",
        return_value={
            "username": "maya",
            "password": "s3cret",
            "host": "127.0.0.1",
            "port": "5432",
            "database": "maya_public",
        },
    ):
        secret = postgres_secret()
        url = database_url()
    assert secret["username"] == "maya"
    assert url.startswith("postgresql+asyncpg://maya:")
    assert "@127.0.0.1:5432/maya_public" in url
    assert "s3cret" in url


def test_env_database_url_wins(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://from-env:pw@localhost:5432/db")
    with patch(
        "services.secrets.openbao.read_secret",
        return_value={"url": "postgresql+asyncpg://from-bao:pw@localhost:5432/db"},
    ):
        assert database_url().startswith("postgresql+asyncpg://from-env:")
        shell = export_postgres_shell()
    assert "DATABASE_URL=" not in shell


def test_export_postgres_shell_sets_libpq(monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.delenv("PGUSER", raising=False)
    with patch(
        "services.secrets.openbao.read_secret",
        return_value={"url": "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/maya_public"},
    ):
        shell = export_postgres_shell()
    assert "export DATABASE_URL=" in shell
    assert "export PGPASSWORD=" in shell
    assert "export PGUSER=postgres" in shell


def test_seed_postgres_from_env(monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/maya_public")
    with patch("services.secrets.openbao.read_secret", return_value={}):
        with patch("services.secrets.openbao.write_secret") as write:
            status = seed_postgres_from_env()
    assert status.startswith("seeded")
    write.assert_called_once()
    path, payload = write.call_args[0]
    assert path == POSTGRES_SECRET_PATH
    assert payload["username"] == "u"
    assert payload["database"] == "maya_public"


def test_apply_database_url_env(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    with patch(
        "services.secrets.openbao.read_secret",
        return_value={"url": "postgresql+asyncpg://bao:pw@127.0.0.1:5432/maya_public"},
    ):
        apply_database_url_env()
    import os

    assert os.environ["DATABASE_URL"].startswith("postgresql+asyncpg://bao:")


def test_bundled_seed_includes_postgres() -> None:
    from services.secrets.openbao import DEV_SEED_EXAMPLE, load_dev_seed

    secrets = load_dev_seed(DEV_SEED_EXAMPLE)
    pg = secrets[POSTGRES_SECRET_PATH]
    assert pg["database"] == "maya_public"
    assert pg["username"] == "postgres"


def test_ensure_local_dev_seed_merges_postgres(tmp_path, monkeypatch) -> None:
    from services.secrets.openbao import (
        SLSKD_SECRET_PATH,
        ensure_local_dev_seed,
    )

    dest = tmp_path / "openbao" / "dev-seed.json"
    dest.parent.mkdir(parents=True)
    dest.write_text(
        json.dumps(
            {
                "secrets": {
                    SLSKD_SECRET_PATH: {
                        "username": "throwaway-user",
                        "password": "keep-me",
                        "network": "soulseek",
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("services.secrets.openbao.DEV_SEED_LOCAL", dest)
    ensure_local_dev_seed()
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["secrets"][SLSKD_SECRET_PATH]["username"] == "throwaway-user"
    assert POSTGRES_SECRET_PATH in payload["secrets"]
