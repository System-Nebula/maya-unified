"""Session log: every turn persisted to SQLite with FTS5 keyword search.

This is the unbounded "cold storage" layer. Unlike curated memory (always in the
prompt) it is searched on demand via the `session_search` tool, so the agent can
recall specifics from conversations weeks ago without paying for them every turn.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Optional


class SessionStore:
    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "state.db")
        self._lock = threading.Lock()
        self._local = threading.local()
        self.session_id = f"sess-{int(time.time())}"
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                ts REAL NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(content, content='messages', content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END;
            """
        )
        conn.commit()

    # ----- writes -----------------------------------------------------------

    def log(self, role: str, content: str) -> None:
        content = (content or "").strip()
        if not content:
            return
        with self._lock:
            conn = self._conn()
            conn.execute(
                "INSERT INTO messages(session_id, ts, role, content) VALUES (?,?,?,?)",
                (self.session_id, time.time(), role, content),
            )
            conn.commit()

    # ----- recent context ---------------------------------------------------

    def recent(self, turns: int) -> list[dict]:
        """Last `turns` user+assistant exchanges from the CURRENT session."""
        limit = max(0, turns) * 2
        if limit == 0:
            return []
        with self._lock:
            rows = self._conn().execute(
                "SELECT role, content FROM messages WHERE session_id=? "
                "AND role IN ('user','assistant') ORDER BY id DESC LIMIT ?",
                (self.session_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # ----- search -----------------------------------------------------------

    def search(self, query: str, limit: int = 6) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        match = self._fts_query(query)
        with self._lock:
            try:
                rows = self._conn().execute(
                    "SELECT m.id, m.session_id, m.ts, m.role, m.content "
                    "FROM messages_fts f JOIN messages m ON m.id = f.rowid "
                    "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # Fall back to LIKE if the FTS query syntax is rejected.
                rows = self._conn().execute(
                    "SELECT id, session_id, ts, role, content FROM messages "
                    "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
        return [self._row(r) for r in rows]

    def context_around(self, message_id: int, before: int = 2, after: int = 2) -> list[dict]:
        with self._lock:
            conn = self._conn()
            row = conn.execute("SELECT session_id FROM messages WHERE id=?", (message_id,)).fetchone()
            if row is None:
                return []
            sid = row["session_id"]
            rows = conn.execute(
                "SELECT id, session_id, ts, role, content FROM messages "
                "WHERE session_id=? AND id BETWEEN ? AND ? ORDER BY id",
                (sid, message_id - before, message_id + after),
            ).fetchall()
        return [self._row(r) for r in rows]

    def sessions(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT session_id, COUNT(*) n, MIN(ts) start, MAX(ts) end "
                "FROM messages GROUP BY session_id ORDER BY start DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"session_id": r["session_id"], "messages": r["n"],
             "start": r["start"], "end": r["end"]}
            for r in rows
        ]

    def browse(
        self,
        limit: int = 50,
        offset: int = 0,
        session_id: Optional[str] = None,
    ) -> dict:
        """Paginated raw message log for the UI explorer."""
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        with self._lock:
            conn = self._conn()
            if session_id:
                total = conn.execute(
                    "SELECT COUNT(*) c FROM messages WHERE session_id=?",
                    (session_id,),
                ).fetchone()["c"]
                rows = conn.execute(
                    "SELECT id, session_id, ts, role, content FROM messages "
                    "WHERE session_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (session_id, limit, offset),
                ).fetchall()
            else:
                total = conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
                rows = conn.execute(
                    "SELECT id, session_id, ts, role, content FROM messages "
                    "ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        return {
            "total": int(total or 0),
            "messages": [self._row(r) for r in rows],
        }

    @staticmethod
    def _fts_query(query: str) -> str:
        # Quote each term so punctuation/operators don't break the MATCH syntax.
        terms = [t for t in query.replace('"', " ").split() if t]
        return " OR ".join(f'"{t}"' for t in terms) if terms else f'"{query}"'

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "session_id": r["session_id"], "ts": r["ts"],
                "role": r["role"], "content": r["content"]}

    # ----- tool -------------------------------------------------------------

    def tool_handler(self, args: dict) -> dict:
        action = (args.get("action") or "search").lower()
        if action == "browse":
            return {"sessions": self.sessions(int(args.get("limit", 20)))}
        if action == "scroll":
            mid = int(args.get("message_id", 0))
            return {"messages": self.context_around(
                mid, int(args.get("before", 2)), int(args.get("after", 2)))}
        results = self.search(str(args.get("query", "")), int(args.get("limit", 6)))
        return {"results": results}
