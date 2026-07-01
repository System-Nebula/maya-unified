"""Minimal auth stubs for self-hosted bot (portal link optional)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PortalUser:
    id: str


async def resolve_discord_user_standalone(discord_user_id: str) -> PortalUser | None:
    return None
