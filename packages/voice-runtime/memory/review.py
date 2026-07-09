"""Background post-turn review: how the agent adapts over time.

After a turn finishes (audio idle), a daemon thread asks the LLM to extract any
durable facts worth remembering from the exchange and writes them to curated,
cognitive, and skill stores. It never blocks the voice loop, and respects
write_approval for curated memory (routing through the same staging path as
the memory tool).
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Callable, Optional

from .scopes import MemoryScope

_REVIEW_PROMPT = (
    "You are the memory-review step for a voice assistant. Read the latest exchange "
    "and extract only DURABLE things worth remembering long-term. Be strict: skip "
    "trivia, small talk, and anything easily re-derived.\n\n"
    "Return ONLY a JSON object with these optional fields (omit empties):\n"
    '{"user": ["stable facts about the person discussed"],\n'
    ' "memory": ["durable conventions, notes, or active/running jokes or bits the assistant should commit to or keep alive in future turns"],\n'
    ' "semantic": ["specific facts for semantic recall"],\n'
    ' "skills": [{"name": "slug-name", "description": "one line summary", '
    '"content": "markdown body with steps — omit if skill already exists unchanged"}]}\n'
    "Keep fact entries one concise sentence. Skills are for REPEATABLE multi-step "
    "workflows the user taught (tool sequences, rituals, formats) — not one-off facts. "
    "Skill content first line should be the description if not already in the field.\n"
    "If nothing is worth saving, return {}.\n\n"
    "Scope context is provided — save facts about the Discord member being discussed "
    "in user/memory, not the voice owner. Server-wide culture/rules go in memory."
)

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


class ReviewEngine:
    def __init__(
        self,
        llm,
        curated,
        cognitive,
        skills,
        enabled: bool = True,
        model: str = "",
        emit: Optional[Callable[..., None]] = None,
    ):
        self.llm = llm
        self.curated = curated
        self.cognitive = cognitive
        self.skills = skills
        self.enabled = enabled
        self.model = model or None
        self._emit = emit

    def schedule(
        self,
        user_text: str,
        reply_text: str,
        scope: Optional[MemoryScope] = None,
    ) -> None:
        if not self.enabled or not reply_text.strip():
            return
        active = scope or MemoryScope()
        threading.Thread(
            target=self._run,
            args=(user_text, reply_text, active),
            daemon=True,
        ).start()

    def _run(self, user_text: str, reply_text: str, scope: MemoryScope) -> None:
        try:
            facts = self._extract(user_text, reply_text, scope)
        except Exception as exc:  # noqa: BLE001 - review must never crash the agent
            print(f"[review] skipped: {exc}")
            return
        if not facts:
            return

        applied = 0
        for entry in facts.get("user", []):
            if self._save_curated("user", entry, scope):
                applied += 1
        for entry in facts.get("memory", []):
            if self._save_curated("memory", entry, scope):
                applied += 1
        if self.cognitive is not None:
            cog_scope = scope.cognitive_store_key()
            for entry in facts.get("semantic", []):
                res = self.cognitive.store(entry, importance=0.6, scope=cog_scope)
                if res.get("success"):
                    applied += 1
        for spec in facts.get("skills", []):
            if self._save_skill(spec):
                applied += 1

        if applied and self._emit is not None:
            self._emit(type="memory_updated", target="review", count=applied)

    def _save_curated(self, target: str, content: str, scope: MemoryScope) -> bool:
        if not content or not content.strip():
            return False
        payload: dict = {
            "action": "add",
            "target": target,
            "content": content.strip(),
            "scope": "global",
            "scope_id": "",
        }
        if scope.discord_user:
            payload["scope"] = "discord_user"
            payload["scope_id"] = scope.discord_user
        elif scope.guild_id or scope.guild_name:
            payload["scope"] = "discord_server"
            payload["scope_id"] = scope.guild_id or scope.guild_name or ""
        res = self.curated.tool_handler(payload, internal=False)
        return bool(res.get("success"))

    def _save_skill(self, spec: Any) -> bool:
        if not isinstance(spec, dict):
            return False
        name = str(spec.get("name") or "").strip()
        content = str(spec.get("content") or "").strip()
        if not name or not content:
            return False
        desc = str(spec.get("description") or "").strip()
        if desc and not content.lstrip().startswith("#"):
            body = f"# {desc}\n\n{content}"
        else:
            body = content
        existing = self.skills.read(name)
        if existing and existing.strip() == body.strip():
            return False
        res = self.skills.write(name, body)
        if res.get("success") and self._emit is not None:
            self._emit(type="skill_updated", name=res.get("name", name))
        return bool(res.get("success"))

    def _extract(
        self,
        user_text: str,
        reply_text: str,
        scope: MemoryScope,
    ) -> Optional[dict]:
        scope_note = "Scope: global (voice owner)."
        if scope.discord_user:
            scope_note = (
                f"Scope: Discord user {scope.discord_user!r}"
                + (f" in server {scope.guild_name!r}" if scope.guild_name else "")
                + ". Facts about this person, not the voice owner."
            )
        elif scope.guild_id or scope.guild_name:
            scope_note = (
                f"Scope: Discord server {scope.guild_name or scope.guild_id!r}. "
                "Server-wide facts, not a specific member profile."
            )
        known_skills = self.skills.list()
        skill_hint = ""
        if known_skills:
            names = ", ".join(s["name"] for s in known_skills[:12])
            skill_hint = f"\nExisting skills (update only if steps changed): {names}"
        messages = [
            {"role": "system", "content": _REVIEW_PROMPT + skill_hint},
            {
                "role": "user",
                "content": (
                    f"{scope_note}\n\n"
                    f"User: {user_text}\nAssistant: {reply_text}"
                ),
            },
        ]
        resp = self.llm.complete(messages, model=self.model, max_tokens=400)
        text = (resp.content or "").strip()
        match = _JSON_OBJ_RE.search(text)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
        except (TypeError, ValueError):
            return None
        if not isinstance(obj, dict):
            return None
        out: dict[str, Any] = {}
        for key in ("user", "memory", "semantic"):
            val = obj.get(key)
            if isinstance(val, str):
                out[key] = [val]
            elif isinstance(val, list):
                out[key] = [str(x) for x in val if str(x).strip()]
        skills_val = obj.get("skills")
        if isinstance(skills_val, dict):
            skills_val = [skills_val]
        if isinstance(skills_val, list):
            out["skills"] = [x for x in skills_val if isinstance(x, dict)]
        return out
