"""Procedural memory: skills the agent can read and write.

Each skill is a markdown file at data/skills/<name>.md whose first line is a short
description. The agent uses the `skill` tool to list/read/write them, and the list
of skill names + descriptions is injected into the session prompt so the agent
knows what procedures it already has.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

from .security import sanitize

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-") or "skill"


class SkillStore:
    def __init__(self, data_dir: str, emit: Optional[Callable[..., None]] = None):
        self.dir = os.path.join(data_dir, "skills")
        os.makedirs(self.dir, exist_ok=True)
        self._emit = emit

    def _path(self, name: str) -> str:
        return os.path.join(self.dir, f"{_slug(name)}.md")

    def list(self) -> list[dict]:
        out: list[dict] = []
        for fname in sorted(os.listdir(self.dir)):
            if not fname.endswith(".md"):
                continue
            path = os.path.join(self.dir, fname)
            desc = ""
            try:
                with open(path, encoding="utf-8") as fh:
                    desc = fh.readline().strip().lstrip("# ").strip()
            except OSError:
                pass
            out.append({"name": fname[:-3], "description": desc})
        return out

    def read(self, name: str) -> Optional[str]:
        path = self._path(name)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    def write(self, name: str, content: str) -> dict:
        ok, cleaned = sanitize(content)
        if not ok:
            return {"success": False, "error": cleaned}
        try:
            with open(self._path(name), "w", encoding="utf-8") as fh:
                fh.write(cleaned)
        except OSError as exc:
            return {"success": False, "error": str(exc)}
        if self._emit is not None:
            self._emit(type="skill_updated", name=_slug(name))
        return {"success": True, "name": _slug(name)}

    def render_index(self) -> str:
        skills = self.list()
        if not skills:
            return ""
        lines = ["=== SKILLS (procedures you know; read with the skill tool) ==="]
        for s in skills:
            lines.append(f"- {s['name']}: {s['description']}" if s["description"] else f"- {s['name']}")
        return "\n".join(lines)

    def tool_handler(self, args: dict) -> dict:
        action = (args.get("action") or "list").lower()
        if action == "list":
            return {"skills": self.list()}
        if action == "read":
            content = self.read(str(args.get("name", "")))
            if content is None:
                return {"success": False, "error": "skill not found"}
            return {"name": args.get("name"), "content": content}
        if action == "write":
            return self.write(str(args.get("name", "")), str(args.get("content", "")))
        return {"success": False, "error": "action must be list, read, or write"}
