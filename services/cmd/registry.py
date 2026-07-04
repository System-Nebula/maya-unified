"""In-memory cmd registry."""

from __future__ import annotations

from services.cmd.models import CmdDefinition, CmdSurface


class CmdRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, CmdDefinition] = {}
        self._alias_index: dict[str, str] = {}

    def register(self, cmd: CmdDefinition) -> None:
        if cmd.id in self._by_id:
            raise ValueError(f"cmd already registered: {cmd.id}")
        self._by_id[cmd.id] = cmd
        self._index_name(cmd.id, cmd.id)
        self._index_name(cmd.name, cmd.id)
        for alias in cmd.aliases:
            self._index_name(alias, cmd.id)

    def _index_name(self, name: str, cmd_id: str) -> None:
        key = (name or "").strip().lower().lstrip("/")
        if not key:
            return
        self._alias_index[key] = cmd_id

    def get(self, cmd_id: str) -> CmdDefinition | None:
        return self._by_id.get(cmd_id)

    def resolve(self, name: str) -> CmdDefinition | None:
        key = (name or "").strip().lower().lstrip("/")
        if not key:
            return None
        cmd_id = self._alias_index.get(key)
        if not cmd_id:
            return None
        return self._by_id.get(cmd_id)

    def list_cmds(
        self,
        *,
        surface: CmdSurface | None = None,
    ) -> list[CmdDefinition]:
        items = list(self._by_id.values())
        if surface is None:
            return sorted(items, key=lambda c: (c.category.lower(), c.name.lower()))
        return sorted(
            [c for c in items if surface in c.surfaces],
            key=lambda c: (c.category.lower(), c.name.lower()),
        )

    def discovery(
        self,
        *,
        surface: CmdSurface | None = None,
    ) -> list[dict]:
        return [cmd.discovery_dict() for cmd in self.list_cmds(surface=surface)]


registry = CmdRegistry()
