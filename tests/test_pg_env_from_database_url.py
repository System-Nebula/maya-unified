"""libpq env from DATABASE_URL — Nix psql against password-auth Postgres."""

from __future__ import annotations

from scripts.pg_env_from_database_url import export_lines, libpq_env


def test_asyncpg_url_sets_password_and_host() -> None:
    env = libpq_env("postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public")
    assert env["PGHOST"] == "localhost"
    assert env["PGPORT"] == "5432"
    assert env["PGUSER"] == "postgres"
    assert env["PGPASSWORD"] == "postgres"
    assert env["PGDATABASE"] == "maya_public"


def test_export_lines_are_shell_safe() -> None:
    text = export_lines("postgresql+asyncpg://u:p%40ss@127.0.0.1:5432/db")
    assert "export PGPASSWORD=" in text
    assert "p@ss" in text
    assert "export PGHOST=127.0.0.1" in text


def test_empty_url() -> None:
    assert libpq_env("") == {}
    assert export_lines("") == ""
