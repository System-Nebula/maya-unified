"""MemoryManager: orchestrates the memory layers and exposes them as tools.

Responsibilities:
  - Build the frozen session prefix (curated memory + skills) for the system prompt.
  - Prefetch semantically-relevant memories before each turn.
  - Provide recent conversation history (DB-backed).
  - Log every turn and kick off the background review.
  - Register the memory/session/cognitive/skill tools.
  - Hold the write-approval staging queue for the UI.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from config import CONFIG
from tools.registry import ToolSpec

from .cognitive import CognitiveMemory
from .curated import CuratedMemory
from .review import ReviewEngine
from .scopes import MemoryScope
from .sessions import SessionStore
from .skills import SkillStore


class MemoryManager:
    def __init__(self, llm, emit=None):
        self.cfg = CONFIG.memory
        self.llm = llm
        self._emit = emit
        self._pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()
        self._bound_data_dir: str | None = None
        self._turn_scope = MemoryScope()
        self._bind_stores(self.cfg.resolve_data_dir())

    def _bind_stores(self, data_dir: str) -> None:
        data_dir = os.path.abspath(data_dir)
        self.curated = CuratedMemory(
            data_dir,
            memory_char_limit=self.cfg.memory_char_limit,
            user_char_limit=self.cfg.user_char_limit,
            write_approval=self.cfg.write_approval,
            stager=self._stage,
            emit=self._emit,
        )
        self.sessions = SessionStore(data_dir)
        self.skills = SkillStore(data_dir, emit=self._emit)
        self.cognitive: Optional[CognitiveMemory] = None
        if self.cfg.cognitive_enabled:
            self.cognitive = CognitiveMemory(data_dir, self.cfg.embed_model, emit=self._emit)
        self.review = ReviewEngine(
            self.llm, self.curated, self.cognitive, self.skills,
            enabled=CONFIG.review.enabled, model=CONFIG.review.model, emit=self._emit,
        )
        self._bound_data_dir = data_dir

    def rebind(self, data_dir: str) -> None:
        """Point all memory stores at a new data directory (per-operator hot-swap)."""
        data_dir = os.path.abspath(data_dir)
        if self._bound_data_dir == data_dir:
            return
        self.cfg.data_dir = data_dir
        with self._pending_lock:
            self._pending.clear()
        self._bind_stores(data_dir)

    def set_turn_scope(self, scope: MemoryScope) -> None:
        self._turn_scope = scope

    def turn_scope(self) -> MemoryScope:
        return self._turn_scope

    # ----- prompt assembly --------------------------------------------------

    def system_suffix(self, scope: Optional[MemoryScope] = None) -> str:
        """Frozen memory + skills block appended to the system prompt at session
        start (kept stable so the prompt prefix can be cached)."""
        parts = [
            b for b in (
                self.curated.render_block(scope),
                self.skills.render_index(),
            ) if b
        ]
        return "\n\n".join(parts)

    def prefetch_context(self, user_text: str, scope: Optional[MemoryScope] = None) -> str:
        """Ephemeral, per-turn recalled memories to prepend to the user message."""
        active = scope or self._turn_scope
        blocks: list[str] = []
        scoped = self.curated.render_block(active)
        global_block = self.curated.render_block(MemoryScope())
        if scoped and scoped != global_block:
            blocks.append(scoped)
        if self.cfg.prefetch and self.cognitive is not None:
            try:
                hits = self.cognitive.recall(
                    user_text,
                    top_k=self.cfg.cognitive_top_k,
                    scopes=active.scope_keys(),
                )
            except Exception:  # noqa: BLE001
                hits = []
            if hits:
                lines = [f"- ({h.get('scope', 'global')}) {h['content']}" for h in hits]
                blocks.append("[Relevant things you recall:\n" + "\n".join(lines) + "\n]")
        if not blocks:
            return ""
        return "\n\n".join(blocks)

    def recent_history(self) -> list[dict]:
        return self.sessions.recent(self.cfg.recent_turns)

    # ----- turn lifecycle ---------------------------------------------------

    def log_turn(self, user_text: str, reply_text: str) -> None:
        self.sessions.log("user", user_text)
        if reply_text:
            self.sessions.log("assistant", reply_text)

    def schedule_review(self, user_text: str, reply_text: str, scope: Optional[MemoryScope] = None) -> None:
        self.review.schedule(user_text, reply_text, scope=scope or self._turn_scope)

    # ----- write-approval staging -------------------------------------------

    def _stage(self, kind: str, payload: dict) -> str:
        sid = f"{kind}-{int(time.time() * 1000)}"
        with self._pending_lock:
            self._pending[sid] = {"id": sid, "kind": kind, "payload": payload, "ts": time.time()}
        return sid

    def pending(self) -> list[dict]:
        with self._pending_lock:
            return list(self._pending.values())

    def approve(self, sid: str) -> dict:
        with self._pending_lock:
            item = self._pending.pop(sid, None)
        if item is None:
            return {"ok": False, "error": "not found"}
        if item["kind"] == "memory":
            res = self.curated.apply_action(item["payload"])
            return {"ok": bool(res.get("success")), **res}
        return {"ok": False, "error": f"unknown kind {item['kind']}"}

    def reject(self, sid: str) -> dict:
        with self._pending_lock:
            existed = self._pending.pop(sid, None) is not None
        return {"ok": existed}

    # ----- status (UI) ------------------------------------------------------

    def status(self) -> dict:
        return {
            "enabled": True,
            "curated": self.curated.snapshot(),
            "cognitive": self.cognitive.status() if self.cognitive else {"total": 0, "loaded": False},
            "skills": self.skills.list(),
            "sessions": self.sessions.sessions(limit=10),
            "pending": self.pending(),
            "write_approval": self.cfg.write_approval,
        }

    def explore_db(
        self,
        db: str,
        limit: int = 50,
        offset: int = 0,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> dict:
        name = (db or "").strip().lower()
        if name in {"state", "sessions", "state.db"}:
            return {"db": "state", **self.sessions.browse(limit, offset, session_id)}
        if name in {"cognitive", "cognitive.db"}:
            if self.cognitive is None:
                return {"db": "cognitive", "total": 0, "entries": [], "enabled": False}
            return {
                "db": "cognitive",
                "enabled": True,
                **self.cognitive.list_entries(limit, offset, scope),
            }
        return {"ok": False, "error": f"unknown database {db!r}"}

    def read_skill(self, name: str) -> Optional[str]:
        return self.skills.read(name)

    # ----- tools ------------------------------------------------------------

    def tools(self) -> list[ToolSpec]:
        specs = [
            ToolSpec(
                name="memory",
                description=(
                    "Save durable facts to persistent memory. target 'user' for "
                    "facts about a person, 'memory' for your own notes/conventions. "
                    "scope 'global' for voice-owner context (default), "
                    "'discord_user' with scope_id=display name for a Discord member, "
                    "'discord_server' with scope_id=guild id or server name for "
                    "server-specific facts."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                        "target": {"type": "string", "enum": ["memory", "user"]},
                        "scope": {
                            "type": "string",
                            "enum": ["global", "discord_user", "discord_server"],
                            "description": "Where to store the fact (default global).",
                        },
                        "scope_id": {
                            "type": "string",
                            "description": "Discord username or server id/name when scoped.",
                        },
                        "content": {"type": "string", "description": "Entry text (for add/replace)."},
                        "old_text": {"type": "string", "description": "Unique substring of the entry to replace/remove."},
                    },
                    "required": ["action"],
                },
                handler=lambda a: self._memory_handler(a),
                group="memory",
            ),
            ToolSpec(
                name="session_search",
                description=(
                    "Search your past conversations. action 'search' with a query, "
                    "'scroll' around a message_id, or 'browse' to list sessions."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search", "scroll", "browse"]},
                        "query": {"type": "string"},
                        "message_id": {"type": "integer"},
                        "before": {"type": "integer"},
                        "after": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["action"],
                },
                handler=lambda a: self.sessions.tool_handler(a),
                group="memory",
            ),
            ToolSpec(
                name="skill",
                description=(
                    "Procedural memory (Hermes-style skills). action 'list' or 'read' "
                    "a skill by name. action 'write' saves a repeatable workflow — "
                    "first line of content is the short description shown in the "
                    "prompt index; rest is markdown steps. Create a skill when the "
                    "user teaches a multi-step procedure, a tool workflow, or "
                    "something you will need again verbatim."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "read", "write"]},
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["action"],
                },
                handler=lambda a: self.skills.tool_handler(a),
                group="memory",
            ),
        ]
        if self.cognitive is not None:
            specs.append(ToolSpec(
                name="cognitive_recall",
                description=(
                    "Semantic long-term memory. action 'recall' by meaning, 'store' a "
                    "fact, 'forget' one, or 'status'. Use scope for discord_user "
                    "(scope_id=name) or discord_server (scope_id=guild) — defaults "
                    "to global. Recall searches global plus active scopes."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["recall", "store", "forget", "status"]},
                        "query": {"type": "string"},
                        "content": {"type": "string"},
                        "importance": {"type": "number"},
                        "top_k": {"type": "integer"},
                        "memory_id": {"type": "integer"},
                        "scope": {
                            "type": "string",
                            "description": "global, user:NAME, or guild:ID for store/recall.",
                        },
                        "scopes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of scope keys to search.",
                        },
                    },
                    "required": ["action"],
                },
                handler=lambda a: self._cognitive_handler(a),
                group="memory",
            ))
        return specs

    def _memory_handler(self, args: dict) -> dict:
        payload = dict(args)
        scope = (payload.get("scope") or "global").lower()
        if scope == "global" and self._turn_scope.discord_user:
            if (payload.get("target") or "memory").lower() == "user":
                payload["scope"] = "discord_user"
                payload["scope_id"] = self._turn_scope.discord_user
        return self.curated.tool_handler(payload)

    def _cognitive_handler(self, args: dict) -> dict:
        payload = dict(args)
        action = (payload.get("action") or "recall").lower()
        if action == "recall" and not payload.get("scopes"):
            scope = (payload.get("scope") or "").strip()
            if not scope or scope == "global":
                payload["scopes"] = self._turn_scope.scope_keys()
        if action == "store" and not (payload.get("scope") or "").strip():
            payload["scope"] = self._turn_scope.cognitive_store_key()
        return self.cognitive.tool_handler(payload)
