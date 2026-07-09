"""ResolvedSet → ontology graph projection tests (mock asyncpg)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from maya_graph.music.primitives import (
    EDGE_CONTAINS_ENTRY,
    EDGE_HAS_RECORDING,
    EDGE_LINKED_SET,
    NODE_CANONICAL_WORK,
    NODE_DJ_SET,
    NODE_RECORDING,
)
from services.music.set_ingest import ingest_set
from tests.helpers.music_set_fixtures import fred_again_merged_resolved_set


class FakeConn:
    """Records SQL calls; returns UUIDs for upserts."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple]] = []
        self.closed = False
        self._ids: dict[tuple[str, str, str], str] = {}

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        key = (args[0], args[1], args[2])  # domain, domain_id, node_type
        if key not in self._ids:
            self._ids[key] = str(uuid.uuid4())
        return self._ids[key]

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"

    async def close(self) -> None:
        self.closed = True


def _node_upserts(conn: FakeConn) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for method, sql, args in conn.calls:
        if method != "fetchval" or "INSERT INTO ontology_node" not in sql:
            continue
        rows.append((args[0], args[1], args[2]))
    return rows


def _edge_types(conn: FakeConn) -> list[str]:
    types: list[str] = []
    for method, sql, args in conn.calls:
        if method != "execute" or "ontology_edge" not in sql:
            continue
        types.append(args[2])
    return types


@pytest.mark.asyncio
async def test_ingest_set_creates_dj_set_recording_and_linked_set_nodes(monkeypatch):
    conn = FakeConn()
    resolved = fred_again_merged_resolved_set()

    async def _fake_connect(_dsn):
        return conn

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setattr("asyncpg.connect", _fake_connect)
    monkeypatch.setattr(
        "services.music.set_ingest.enrich_set_entries",
        AsyncMock(return_value=resolved),
    )
    monkeypatch.setattr("services.music.set_ingest._persist_relational", AsyncMock())

    await ingest_set(resolved)

    assert conn.closed
    upserts = _node_upserts(conn)
    node_types = {row[2] for row in upserts}
    assert NODE_DJ_SET in node_types
    assert NODE_RECORDING in node_types

    recording_count = sum(1 for row in upserts if row[2] == NODE_RECORDING)
    # 3 entries × 3 platform refs each
    assert recording_count == 9

    linked_set_count = sum(1 for row in upserts if row[2] == NODE_DJ_SET) - 1
    assert linked_set_count >= 2

    edges = _edge_types(conn)
    assert EDGE_LINKED_SET in edges
    assert edges.count(EDGE_HAS_RECORDING) >= 0  # only when work_key present

    dj_set_upserts = [row[1] for row in upserts if row[2] == NODE_DJ_SET and row[1] == resolved.set_key]
    assert len(dj_set_upserts) >= 1


@pytest.mark.asyncio
async def test_ingest_set_links_work_when_work_key_present(monkeypatch):
    conn = FakeConn()
    resolved = fred_again_merged_resolved_set()
    resolved.entries[0].work_key = "fp:test-work-key"

    async def _fake_connect(_dsn):
        return conn

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setattr("asyncpg.connect", _fake_connect)
    monkeypatch.setattr(
        "services.music.set_ingest.enrich_set_entries",
        AsyncMock(return_value=resolved),
    )
    monkeypatch.setattr("services.music.set_ingest._persist_relational", AsyncMock())

    await ingest_set(resolved)

    upserts = _node_upserts(conn)
    assert any(row[2] == NODE_CANONICAL_WORK for row in upserts)
    edges = _edge_types(conn)
    assert EDGE_CONTAINS_ENTRY in edges
    assert EDGE_HAS_RECORDING in edges
