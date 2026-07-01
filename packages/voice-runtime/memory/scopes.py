"""Memory scope keys — global, per-Discord-user, per-Discord-server."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


def safe_scope_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_-]", "_", (value or "").strip().lower())
    return (key[:64] or "unknown").strip("_")


@dataclass
class MemoryScope:
    """Active context for the current turn."""

    guild_id: Optional[str] = None
    guild_name: Optional[str] = None
    discord_user: Optional[str] = None

    def scope_keys(self) -> list[str]:
        """Cognitive recall keys — always include global, plus active scopes."""
        keys = ["global"]
        if self.guild_id:
            keys.append(f"guild:{safe_scope_key(self.guild_id)}")
        elif self.guild_name:
            keys.append(f"guild:{safe_scope_key(self.guild_name)}")
        if self.discord_user:
            keys.append(f"user:{safe_scope_key(self.discord_user)}")
        return keys

    def is_scoped(self) -> bool:
        return bool(self.guild_id or self.guild_name or self.discord_user)

    def cognitive_store_key(self) -> str:
        """Primary cognitive scope for store/review on this turn."""
        if self.discord_user:
            return f"user:{safe_scope_key(self.discord_user)}"
        if self.guild_id:
            return f"guild:{safe_scope_key(self.guild_id)}"
        if self.guild_name:
            return f"guild:{safe_scope_key(self.guild_name)}"
        return "global"
