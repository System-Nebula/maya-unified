"""Sync PostgreSQL connection for bot/image services."""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


class PostgresConnection:
    """Manages synchronous PostgreSQL connections via DATABASE_URL."""

    def __init__(self) -> None:
        self.database_url = self._resolve_database_url()
        parsed = urlparse(self.database_url)
        self.host = parsed.hostname or os.getenv("POSTGRES_HOST", "localhost")
        self.port = str(parsed.port or os.getenv("POSTGRES_PORT", "5432"))
        self.user = parsed.username or os.getenv("POSTGRES_USER", "postgres")
        self.password = parsed.password or os.getenv("POSTGRES_PASSWORD", "")
        self.dbname = (parsed.path or "/postgres").lstrip("/") or "postgres"
        self._engine = None
        self._session_factory: sessionmaker[Session] | None = None

    def _resolve_database_url(self) -> str:
        raw_url = (
            os.getenv("MAYA_DATABASE_URL")
            or os.getenv("DATABASE_URL")
            or os.getenv("POSTGRES_URL")
        )
        if raw_url:
            for prefix in ("postgresql+asyncpg://", "postgresql+async://"):
                if raw_url.startswith(prefix):
                    return raw_url.replace(prefix, "postgresql://", 1)
            return raw_url

        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "")
        dbname = os.getenv("POSTGRES_DB", "postgres")
        netloc = f"{user}:{password}@{host}:{port}" if password else f"{user}@{host}:{port}"
        return urlunparse(("postgresql", netloc, f"/{dbname}", "", "", ""))

    def get_engine(self):
        if self._engine is None:
            self._engine = create_engine(
                self.database_url,
                pool_pre_ping=True,
                pool_recycle=300,
                connect_args={"connect_timeout": 5},
            )
        return self._engine

    def get_session(self) -> Session:
        if self._session_factory is None:
            self._session_factory = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.get_engine(),
            )
        return self._session_factory()


_connection: Optional[PostgresConnection] = None


def get_sync_connection() -> PostgresConnection:
    global _connection
    if _connection is None:
        _connection = PostgresConnection()
    return _connection
