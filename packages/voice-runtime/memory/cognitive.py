"""Cognitive (semantic) memory: meaning-based recall over a local vector store.

Inspired by Hermes' cognitive memory. Facts are embedded with a small local model
(`fastembed`, CPU) and stored in SQLite as packed float32 vectors. Recall combines
similarity, recency, and importance into one composite score, and low-value stale
memories can be forgotten.

The embedder is loaded lazily on first use so the dependency is only paid for when
cognitive memory is actually enabled and exercised.
"""

from __future__ import annotations

import math
import os
import sqlite3
import struct
import threading
import time
from typing import Optional

from .security import sanitize

# Composite recall weights (similarity / recency / importance).
_W_SIM, _W_RECENCY, _W_IMPORTANCE = 0.5, 0.3, 0.2
# Recency half-life in days for the recency score.
_RECENCY_HALFLIFE_DAYS = 14.0


class CognitiveMemory:
    def __init__(self, data_dir: str, embed_model: str, emit=None):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "cognitive.db")
        self.embed_model = embed_model
        self._emit = emit
        self._lock = threading.Lock()
        self._local = threading.local()
        self._embedder = None
        self._embedder_lock = threading.Lock()
        self._dim: Optional[int] = None
        self._init_db()

    # ----- storage ----------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        self._conn().executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                content TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                embedding BLOB NOT NULL,
                superseded INTEGER NOT NULL DEFAULT 0,
                scope TEXT NOT NULL DEFAULT 'global'
            );
            """
        )
        try:
            self._conn().execute(
                "ALTER TABLE memories ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'"
            )
            self._conn().commit()
        except sqlite3.OperationalError:
            pass
        self._conn().commit()

    # ----- embeddings -------------------------------------------------------

    def _embed(self, text: str) -> Optional[list[float]]:
        if self._embedder is None:
            with self._embedder_lock:
                if self._embedder is None:
                    try:
                        from fastembed import TextEmbedding

                        print(f"[memory] loading embedding model {self.embed_model} (first use)...")
                        self._embedder = TextEmbedding(model_name=self.embed_model)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[memory] cognitive memory disabled (embeddings unavailable): {exc}")
                        return None
        try:
            vec = list(next(iter(self._embedder.embed([text]))))
        except Exception as exc:  # noqa: BLE001
            print(f"[memory] embedding failed: {exc}")
            return None
        self._dim = len(vec)
        return [float(x) for x in vec]

    @staticmethod
    def _pack(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _unpack(blob: bytes) -> list[float]:
        return list(struct.unpack(f"{len(blob) // 4}f", blob))

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    # ----- operations -------------------------------------------------------

    def store(self, content: str, importance: float = 0.5, scope: str = "global") -> dict:
        ok, cleaned = sanitize(content)
        if not ok:
            return {"success": False, "error": cleaned}
        vec = self._embed(cleaned)
        if vec is None:
            return {"success": False, "error": "embeddings unavailable"}
        importance = max(0.0, min(1.0, float(importance)))
        scope_key = (scope or "global").strip() or "global"
        # Contradiction/duplicate check within the same scope.
        superseded = 0
        for hit in self._scored(vec, limit=1, threshold=0.0, scopes=[scope_key]):
            if hit["similarity"] >= 0.93:
                with self._lock:
                    self._conn().execute(
                        "UPDATE memories SET superseded=1 WHERE id=?", (hit["id"],))
                    self._conn().commit()
                superseded = hit["id"]
        with self._lock:
            self._conn().execute(
                "INSERT INTO memories(ts, content, importance, embedding, scope) "
                "VALUES (?,?,?,?,?)",
                (time.time(), cleaned, importance, self._pack(vec), scope_key),
            )
            self._conn().commit()
        if self._emit is not None:
            self._emit(type="memory_updated", target="cognitive", action="store", scope=scope_key)
        return {"success": True, "superseded": superseded, "scope": scope_key}

    def recall(
        self,
        query: str,
        top_k: int = 4,
        scopes: Optional[list[str]] = None,
    ) -> list[dict]:
        vec = self._embed(query)
        if vec is None:
            return []
        scope_list = scopes or ["global"]
        return self._scored(vec, limit=top_k, threshold=0.2, scopes=scope_list)

    def _scored(
        self,
        vec: list[float],
        limit: int,
        threshold: float,
        scopes: Optional[list[str]] = None,
    ) -> list[dict]:
        scope_list = scopes or ["global"]
        placeholders = ",".join("?" for _ in scope_list)
        with self._lock:
            rows = self._conn().execute(
                f"SELECT id, ts, content, importance, embedding, scope "
                f"FROM memories WHERE superseded=0 AND scope IN ({placeholders})",
                scope_list,
            ).fetchall()
        now = time.time()
        scored: list[dict] = []
        for r in rows:
            sim = self._cosine(vec, self._unpack(r["embedding"]))
            if sim < threshold:
                continue
            age_days = max(0.0, (now - r["ts"]) / 86400.0)
            recency = math.exp(-age_days / _RECENCY_HALFLIFE_DAYS)
            score = _W_SIM * sim + _W_RECENCY * recency + _W_IMPORTANCE * r["importance"]
            scored.append({
                "id": r["id"], "content": r["content"], "similarity": round(sim, 4),
                "score": round(score, 4), "importance": r["importance"], "ts": r["ts"],
                "scope": r["scope"] if "scope" in r.keys() else "global",
            })
        scored.sort(key=lambda m: m["score"], reverse=True)
        return scored[:limit]

    def forget(self, query: str, memory_id: Optional[int] = None) -> dict:
        with self._lock:
            conn = self._conn()
            if memory_id is not None:
                conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
                conn.commit()
                return {"success": True, "deleted": memory_id}
        hits = self.recall(query, top_k=1)
        if not hits:
            return {"success": False, "error": "no matching memory"}
        with self._lock:
            self._conn().execute("DELETE FROM memories WHERE id=?", (hits[0]["id"],))
            self._conn().commit()
        return {"success": True, "deleted": hits[0]["id"]}

    def prune(self, max_entries: int = 500) -> int:
        """Drop the lowest-importance, oldest memories beyond max_entries."""
        with self._lock:
            conn = self._conn()
            total = conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
            if total <= max_entries:
                return 0
            to_drop = total - max_entries
            conn.execute(
                "DELETE FROM memories WHERE id IN ("
                "SELECT id FROM memories ORDER BY importance ASC, ts ASC LIMIT ?)",
                (to_drop,),
            )
            conn.commit()
        return to_drop

    def status(self) -> dict:
        with self._lock:
            row = self._conn().execute(
                "SELECT COUNT(*) c, SUM(superseded) s FROM memories"
            ).fetchone()
        return {"total": row["c"] or 0, "superseded": row["s"] or 0,
                "model": self.embed_model, "loaded": self._embedder is not None}

    def list_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        scope: Optional[str] = None,
        include_superseded: bool = False,
    ) -> dict:
        """Paginated cognitive memories for the UI explorer."""
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        clauses = ["1=1"]
        params: list = []
        if not include_superseded:
            clauses.append("superseded=0")
        if scope:
            clauses.append("scope=?")
            params.append(scope.strip())
        where = " AND ".join(clauses)
        with self._lock:
            conn = self._conn()
            total = conn.execute(
                f"SELECT COUNT(*) c FROM memories WHERE {where}",
                params,
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT id, ts, content, importance, scope, superseded "
                f"FROM memories WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return {
            "total": int(total or 0),
            "entries": [
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "content": r["content"],
                    "importance": r["importance"],
                    "scope": r["scope"] if "scope" in r.keys() else "global",
                    "superseded": bool(r["superseded"]),
                }
                for r in rows
            ],
        }

    # ----- tool -------------------------------------------------------------

    def tool_handler(self, args: dict) -> dict:
        action = (args.get("action") or "recall").lower()
        scope = str(args.get("scope") or "global").strip() or "global"
        if action == "store":
            return self.store(
                str(args.get("content", "")),
                float(args.get("importance", 0.5)),
                scope=scope,
            )
        if action == "forget":
            mid = args.get("memory_id")
            return self.forget(str(args.get("query", "")), int(mid) if mid is not None else None)
        if action == "status":
            return self.status()
        scopes = args.get("scopes")
        if isinstance(scopes, list) and scopes:
            scope_list = [str(s) for s in scopes]
        else:
            scope_list = [scope] if scope != "global" else ["global"]
            if scope == "global":
                scope_list = ["global"]
        return {
            "results": self.recall(
                str(args.get("query", "")),
                int(args.get("top_k", 4)),
                scopes=scope_list,
            )
        }
