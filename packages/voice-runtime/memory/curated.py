"""Curated persistent memory: MEMORY.md (agent notes) and USER.md (user profile).

Mirrors Hermes' bounded, self-curated memory. Both files are `§`-delimited entry
lists rendered into the system prompt as a frozen snapshot at session start. The
agent edits them at runtime via the `memory` tool (add / replace / remove); writes
persist to disk immediately but only refresh in the prompt next session.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from .scopes import MemoryScope, safe_scope_key
from .security import sanitize

_DELIM = "\n§\n"


class _Store:
    def __init__(self, path: str, label: str, char_limit: int):
        self.path = path
        self.label = label
        self.char_limit = char_limit
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def entries(self) -> list[str]:
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            return []
        return [e.strip() for e in raw.split("§") if e.strip()]

    def _write(self, entries: list[str]) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(_DELIM.join(entries))

    def used(self) -> int:
        return sum(len(e) for e in self.entries())

    def add(self, content: str) -> dict:
        ok, cleaned = sanitize(content)
        if not ok:
            return {"success": False, "error": cleaned}
        entries = self.entries()
        if cleaned in entries:
            return {"success": True, "note": "no duplicate added"}
        projected = self.used() + len(cleaned)
        if projected > self.char_limit:
            return {
                "success": False,
                "error": (
                    f"{self.label} at {self.used()}/{self.char_limit} chars. Adding this "
                    f"entry ({len(cleaned)} chars) would exceed the limit. Consolidate: "
                    "use replace to merge entries or remove stale ones, then retry."
                ),
                "current_entries": entries,
            }
        entries.append(cleaned)
        self._write(entries)
        return {"success": True, "usage": f"{self.used()}/{self.char_limit}"}

    def replace(self, old_text: str, content: str) -> dict:
        ok, cleaned = sanitize(content)
        if not ok:
            return {"success": False, "error": cleaned}
        entries = self.entries()
        matches = [i for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return {"success": False, "error": f"no entry matches '{old_text}'"}
        if len(matches) > 1:
            return {"success": False, "error": f"'{old_text}' matches {len(matches)} entries; be more specific"}
        entries[matches[0]] = cleaned
        if sum(len(e) for e in entries) > self.char_limit:
            return {"success": False, "error": "replacement would exceed the char limit; shorten it"}
        self._write(entries)
        return {"success": True, "usage": f"{self.used()}/{self.char_limit}"}

    def remove(self, old_text: str) -> dict:
        entries = self.entries()
        matches = [i for i, e in enumerate(entries) if old_text in e]
        if not matches:
            return {"success": False, "error": f"no entry matches '{old_text}'"}
        if len(matches) > 1:
            return {"success": False, "error": f"'{old_text}' matches {len(matches)} entries; be more specific"}
        del entries[matches[0]]
        self._write(entries)
        return {"success": True, "usage": f"{self.used()}/{self.char_limit}"}

    def render(self) -> str:
        entries = self.entries()
        if not entries:
            return ""
        used = self.used()
        pct = round(100 * used / self.char_limit) if self.char_limit else 0
        header = f"=== {self.label} [{pct}% - {used}/{self.char_limit} chars] ==="
        return header + "\n" + "\n§\n".join(entries)


class CuratedMemory:
    def __init__(self, data_dir: str, memory_char_limit: int, user_char_limit: int,
                 write_approval: bool = False,
                 stager: Optional[Callable[[str, dict], str]] = None,
                 emit: Optional[Callable[..., None]] = None):
        mem_dir = os.path.join(data_dir, "memory")
        self._mem_dir = mem_dir
        self.memory = _Store(os.path.join(mem_dir, "MEMORY.md"), "MEMORY (your personal notes)", memory_char_limit)
        self.user = _Store(os.path.join(mem_dir, "USER.md"), "USER PROFILE (voice owner)", user_char_limit)
        self._scoped_user_limit = max(400, user_char_limit)
        self._scoped_guild_limit = max(400, memory_char_limit)
        self.write_approval = write_approval
        self._stager = stager
        self._emit = emit

    def _scoped_user_path(self, user_key: str) -> str:
        return os.path.join(self._mem_dir, "users", f"{safe_scope_key(user_key)}.md")

    def _scoped_guild_path(self, guild_key: str) -> str:
        return os.path.join(self._mem_dir, "guilds", f"{safe_scope_key(guild_key)}.md")

    def discord_user_store(self, user_key: str) -> _Store:
        label = f"DISCORD USER: {user_key}"
        return _Store(self._scoped_user_path(user_key), label, self._scoped_user_limit)

    def discord_guild_store(self, guild_key: str, guild_name: str = "") -> _Store:
        label = f"DISCORD SERVER: {guild_name or guild_key}"
        return _Store(self._scoped_guild_path(guild_key), label, self._scoped_guild_limit)

    def _store(self, target: str, scope: str = "global", scope_id: str = "") -> _Store:
        target = (target or "memory").lower()
        scope = (scope or "global").lower()
        if scope == "discord_user" and scope_id:
            return self.discord_user_store(scope_id)
        if scope == "discord_server" and scope_id:
            return self.discord_guild_store(scope_id)
        return self.user if target == "user" else self.memory

    def render_block(self, scope: Optional[MemoryScope] = None) -> str:
        parts = [b for b in (self.memory.render(), self.user.render()) if b]
        if scope is not None:
            if scope.discord_user:
                block = self.discord_user_store(scope.discord_user).render()
                if block:
                    parts.append(block)
            guild_key = scope.guild_id or scope.guild_name
            if guild_key:
                block = self.discord_guild_store(guild_key, scope.guild_name or "").render()
                if block:
                    parts.append(block)
        return "\n\n".join(parts)

    def snapshot(self) -> dict:
        return {
            "memory": self.memory.entries(),
            "user": self.user.entries(),
            "memory_usage": f"{self.memory.used()}/{self.memory.char_limit}",
            "user_usage": f"{self.user.used()}/{self.user.char_limit}",
        }

    def apply_action(self, payload: dict) -> dict:
        """Apply a memory edit directly (used on approval and for free writes)."""
        action = (payload.get("action") or "").lower()
        store = self._store(
            payload.get("target", "memory"),
            scope=str(payload.get("scope") or "global"),
            scope_id=str(payload.get("scope_id") or ""),
        )
        if action == "add":
            res = store.add(payload.get("content", ""))
        elif action == "replace":
            res = store.replace(payload.get("old_text", ""), payload.get("content", ""))
        elif action == "remove":
            res = store.remove(payload.get("old_text", ""))
        else:
            return {"success": False, "error": f"unknown action '{action}'"}
        if res.get("success") and self._emit is not None:
            self._emit(type="memory_updated", target=payload.get("target", "memory"), action=action)
        return res

    def tool_handler(self, args: dict, internal: bool = False) -> dict:
        action = (args.get("action") or "").lower()
        if action not in {"add", "replace", "remove"}:
            return {"success": False, "error": "action must be add, replace, or remove"}
        payload = {
            "action": action,
            "target": (args.get("target") or "memory").lower(),
            "scope": (args.get("scope") or "global").lower(),
            "scope_id": str(args.get("scope_id") or ""),
            "old_text": args.get("old_text", ""),
            "content": args.get("content", ""),
        }
        if self.write_approval and not internal and self._stager is not None:
            sid = self._stager("memory", payload)
            if self._emit is not None:
                self._emit(type="memory_pending", id=sid, action=action, target=payload["target"])
            return {"success": True, "staged": sid, "note": "write staged for approval"}
        return self.apply_action(payload)
