#!/usr/bin/env python3
"""Print `export PG*` lines from DATABASE_URL for libpq clients (psql, pg_isready).

Nix puts `psql` on PATH. GitHub Actions Postgres uses password auth, so a bare
`psql -h 127.0.0.1 -U postgres` prompts and fails with "no password supplied".
"""

from __future__ import annotations

import os
import shlex
import sys
from urllib.parse import unquote, urlparse


def libpq_env(database_url: str) -> dict[str, str]:
    raw = (database_url or "").strip()
    if not raw:
        return {}
    for prefix in (
        "postgresql+asyncpg://",
        "postgres+asyncpg://",
        "postgresql+psycopg://",
        "postgres+psycopg://",
        "postgresql+psycopg2://",
    ):
        if raw.startswith(prefix):
            raw = "postgresql://" + raw[len(prefix) :]
            break
    parsed = urlparse(raw)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return {}
    env: dict[str, str] = {}
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    db = (parsed.path or "").lstrip("/").split("/")[0]
    if db:
        env["PGDATABASE"] = db
    return env


def export_lines(database_url: str) -> str:
    parts = []
    for key, value in libpq_env(database_url).items():
        parts.append(f"export {key}={shlex.quote(value)}")
    return "\n".join(parts)


def main() -> int:
    print(export_lines(os.environ.get("DATABASE_URL", "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
