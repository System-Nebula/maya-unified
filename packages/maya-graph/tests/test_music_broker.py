"""Tests for MusicQueryBroker — fake asyncpg conn, no network/DB."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from maya_graph.music.broker import MusicQueryBroker
from maya_graph.music.primitives import (
    ArtistRef,
    CanonicalWork,
    Recording,
    RecordingQuery,
    ResolutionEvent,
    SourceRef,
    WorkQuery,
)

FAKE_DSN = "postgresql://fake:fake@nowhere:5432/fake"


class FakeConn:
    """Records every (method, sql, args) call; returns canned results."""

    def __init__(self, *, rows=None, row=None):
        self.calls: list[tuple[str, str, tuple]] = []
        self._rows = rows or []
        self._row = row
        self.closed = False

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._rows

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._row

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return str(uuid.uuid4())

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"

    async def close(self):
        self.closed = True


class StubSchema:
    """SourceSchema stub returning a fixed work; records invocations."""

    schema_id = "stub"

    def __init__(self, works=(), recordings=()):
        self.works = list(works)
        self.recordings = list(recordings)
        self.queries: list[WorkQuery] = []

    async def search_work(self, query):
        self.queries.append(query)
        return list(self.works)

    async def fetch_recording(self, ref):
        return None

    async def fetch_recordings(self, work):
        return list(self.recordings)


def make_broker(conn, **kwargs) -> MusicQueryBroker:
    broker = MusicQueryBroker(dsn=FAKE_DSN, **kwargs)

    async def _connect():
        return conn

    broker._connect = _connect  # type: ignore[method-assign]
    return broker


async def drain_bg(broker: MusicQueryBroker) -> None:
    while broker._bg_tasks:
        await asyncio.gather(*list(broker._bg_tasks), return_exceptions=True)


WORK_ROW = {
    "id": uuid.uuid4(),
    "domain_id": "wd:Q1",
    "label": "Midnight City",
    "attrs": {"aliases": ["Midnight City (M83)"]},
}


async def test_no_dsn_short_circuits_without_connecting(monkeypatch) -> None:
    monkeypatch.delenv("MAYA_ONTOLOGY_DSN", raising=False)
    broker = MusicQueryBroker()  # no dsn, no schemas

    async def boom():  # would explode if the broker tried to connect
        raise AssertionError("must not connect without a DSN")

    broker._connect = boom  # type: ignore[method-assign]
    assert await broker.resolve_work(WorkQuery(text="anything")) == []
    assert await broker.resolve_recording(RecordingQuery(work_key="wd:Q1")) is None


async def test_graph_hit_skips_schemas_and_is_parameterized() -> None:
    conn = FakeConn(rows=[WORK_ROW])
    schema = StubSchema()
    broker = make_broker(conn, schemas=[schema])

    candidates = await broker.resolve_work(WorkQuery(text="midnight city"))

    assert candidates and candidates[0].confidence == 1.0
    assert candidates[0].node_id == str(WORK_ROW["id"])
    assert candidates[0].work.key == "wd:Q1"
    assert schema.queries == []  # confident graph hit → schema never consulted
    assert conn.closed

    method, sql, args = conn.calls[0]
    assert method == "fetch"
    # values travel as $n args, never interpolated into SQL text
    assert "midnight city" not in sql
    assert "midnight city" in args
    assert "$1" in sql and "$2" in sql


async def test_exact_source_ref_lookup_uses_domain_id() -> None:
    conn = FakeConn(rows=[WORK_ROW])
    broker = make_broker(conn)

    ref = SourceRef(schema="wd", external_id="Q1")
    candidates = await broker.resolve_work(WorkQuery(source_ref=ref))

    assert candidates[0].confidence == 1.0
    _, sql, args = conn.calls[0]
    assert "domain_id" in sql
    assert "wd:Q1" in args


async def test_graph_miss_consults_schema_and_writes_through() -> None:
    conn = FakeConn(rows=[])
    work = CanonicalWork(
        key="wd:Q2",
        label="Infinite Falling Ground",
        anchors=(SourceRef(schema="wd", external_id="Q2"),),
        artists=(ArtistRef(slug="ivy-lab", name="Ivy Lab"),),
    )
    schema = StubSchema(works=[work])
    broker = make_broker(conn, schemas=[schema])

    candidates = await broker.resolve_work(WorkQuery(text="infinite falling ground"))
    await drain_bg(broker)

    assert candidates[0].work.key == "wd:Q2"
    assert candidates[0].node_id is None  # write-through async, node id unknown
    assert len(schema.queries) == 1

    upserts = [c for c in conn.calls if c[0] == "fetchval"]
    assert upserts, "write-through should upsert nodes"
    node_sql = upserts[0][1]
    assert "ON CONFLICT (domain, domain_id, node_type)" in node_sql
    assert "attrs = ontology_node.attrs || EXCLUDED.attrs" in node_sql  # merge, not clobber
    # artist node + performed_by edge
    edge_calls = [c for c in conn.calls if c[0] == "execute"]
    assert any("ontology_edge" in sql for _, sql, _ in edge_calls)


async def test_schema_fetch_recordings_included_in_write_through() -> None:
    conn = FakeConn(rows=[])
    work = CanonicalWork(key="wd:Q130464775", label="Despacito")
    recording = Recording(
        source=SourceRef(schema="yt", external_id="t3IyUATcAbE"),
        title="Despacito",
        webpage_url="https://youtu.be/t3IyUATcAbE",
    )
    schema = StubSchema(works=[work], recordings=[recording])
    broker = make_broker(conn, schemas=[schema])

    await broker.resolve_work(WorkQuery(text="despacito"))
    await drain_bg(broker)

    # work node + recording node upserted
    upserts = [c for c in conn.calls if c[0] == "fetchval"]
    assert len(upserts) >= 2
    edge_calls = [c for c in conn.calls if c[0] == "execute"]
    assert any("has_recording" in args for _, _, args in edge_calls)


async def test_failing_schema_is_tolerated() -> None:
    conn = FakeConn(rows=[])

    class ExplodingSchema:
        schema_id = "boom"

        async def search_work(self, query):
            raise RuntimeError("upstream down")

        async def fetch_recording(self, ref):
            return None

    fallback = StubSchema(works=[CanonicalWork(key="wd:Q3", label="Fallback Song")])
    broker = make_broker(conn, schemas=[ExplodingSchema(), fallback])

    candidates = await broker.resolve_work(WorkQuery(text="fallback song"))
    await drain_bg(broker)

    assert candidates and candidates[0].work.key == "wd:Q3"


async def test_resolve_recording_by_work_key_parameterized() -> None:
    rec_row = {
        "id": uuid.uuid4(),
        "domain_id": "yt:abc123",
        "label": "Midnight City",
        "attrs": {"webpage_url": "https://youtu.be/abc123", "title": "Midnight City"},
    }
    conn = FakeConn(row=rec_row)
    broker = make_broker(conn)

    rec = await broker.resolve_recording(RecordingQuery(work_key="wd:Q1"))

    assert rec is not None
    assert rec.source.schema == "yt"
    assert rec.source.external_id == "abc123"
    assert rec.webpage_url == "https://youtu.be/abc123"
    _, sql, args = conn.calls[0]
    assert "wd:Q1" in args and "wd:Q1" not in sql
    assert "has_recording" in args  # edge type also parameterized


async def test_ingest_emits_on_resolution_and_returns_node_id() -> None:
    conn = FakeConn()
    events: list[ResolutionEvent] = []

    async def hook(event: ResolutionEvent) -> None:
        events.append(event)

    broker = make_broker(conn, on_resolution=hook)
    event = ResolutionEvent(
        work=CanonicalWork(key="fp:m83::midnight-city::::original", label="Midnight City"),
        recordings=(
            Recording(
                source=SourceRef(schema="bandcamp", external_id="m83/midnight-city"),
                title="Midnight City",
            ),
        ),
        source_schema="bandcamp",
        confidence=0.9,
    )

    node_id = await broker.ingest(event)

    assert node_id is not None
    assert events == [event]
    # work + recording nodes upserted, has_recording edge linked
    assert len([c for c in conn.calls if c[0] == "fetchval"]) == 2
    assert any("ontology_edge" in sql for m, sql, _ in conn.calls if m == "execute")


async def test_hook_failure_does_not_break_ingest() -> None:
    conn = FakeConn()

    async def bad_hook(event):
        raise RuntimeError("db down")

    broker = make_broker(conn, on_resolution=bad_hook)
    event = ResolutionEvent(
        work=CanonicalWork(key="wd:Q9", label="X"),
        recordings=(),
        source_schema="wd",
        confidence=0.5,
    )
    assert await broker.ingest(event) is not None
