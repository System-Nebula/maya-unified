"""Poll browser_capture_outbox and project captures into MDX + ontology."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import asyncpg
import httpx

from services.browser.config import ENRICHd_URL
from services.browser.mdx_writer import write_capture_artifacts
from services.browser.projector import project_browser_capture

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = float(os.environ.get("BROWSER_CAPTURE_POLL_SEC", "2.0"))
BATCH_SIZE = int(os.environ.get("BROWSER_CAPTURE_BATCH_SIZE", "10"))


def _asyncpg_dsn() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public")
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres+asyncpg://", "postgresql://")


async def _fetch_pending(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT o.id AS outbox_id, o.payload, c.*
        FROM browser_capture_outbox o
        JOIN captures c ON c.capture_id = o.capture_id
        WHERE o.processed_at IS NULL
        ORDER BY o.created_at
        LIMIT $1
        FOR UPDATE OF o SKIP LOCKED
        """,
        BATCH_SIZE,
    )


async def _mark_processed(conn: asyncpg.Connection, outbox_id, capture_id) -> None:
    now = datetime.now(timezone.utc)
    await conn.execute(
        "UPDATE browser_capture_outbox SET processed_at = $1 WHERE id = $2",
        now,
        outbox_id,
    )
    await conn.execute(
        "UPDATE captures SET processed_at = $1 WHERE capture_id = $2",
        now,
        capture_id,
    )


async def _maybe_enrich(capture_id: str, title: str, reader_text: str) -> None:
    if not ENRICHd_URL:
        return
    text = (reader_text or title or "")[:8000]
    if not text.strip():
        return
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{ENRICHd_URL}/embed",
                json={"capture_id": capture_id, "text": text},
            )
    except Exception as exc:
        log.debug("enrichd embed stub skipped: %s", exc)


async def process_one(conn: asyncpg.Connection, row: asyncpg.Record) -> None:
    payload = row["payload"]
    if isinstance(payload, str):
        import json

        payload = json.loads(payload)

    capture_id = str(row["capture_id"])
    title = row["title"] or ""
    reader_text = row["reader_text"] or ""
    selection = row["selection"] or ""
    assets = row["assets"] or []
    if isinstance(assets, str):
        import json

        assets = json.loads(assets)

    write_capture_artifacts(
        capture_id=capture_id,
        capture_type=row["capture_type"],
        url=row["url"],
        title=title,
        content_hash=row["content_hash"],
        tags=row["tags"] or [],
        reader_text=reader_text,
        selection=selection,
        assets=assets,
        metadata=row["metadata"] or {},
        received_at=row["received_at"],
    )

    await project_browser_capture(
        conn,
        capture_id=capture_id,
        url=row["url"],
        title=title,
        capture_type=row["capture_type"],
        assets=assets,
    )

    await _maybe_enrich(capture_id, title, reader_text)
    await _mark_processed(conn, row["outbox_id"], row["capture_id"])
    log.info("processed browser capture %s", capture_id)


async def run_once() -> int:
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        async with conn.transaction():
            rows = await _fetch_pending(conn)
            for row in rows:
                await process_one(conn, row)
        return len(rows)
    finally:
        await conn.close()


async def run_loop() -> None:
    log.info("browser capture worker started (dsn=%s)", _asyncpg_dsn().split("@")[-1])
    while True:
        try:
            count = await run_once()
            if count == 0:
                await asyncio.sleep(POLL_INTERVAL_SEC)
        except Exception:
            log.exception("browser capture worker iteration failed")
            await asyncio.sleep(POLL_INTERVAL_SEC)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_loop())


if __name__ == "__main__":
    main()
