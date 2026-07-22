"""Opt-in Ax (ax-llm) tool router for the voice agent.

The Ax counterpart to ``dspy_router.DspyRouter``: given a user utterance and the
live tool catalog, decide which tool (if any) to call and with what arguments.
It talks to the same OpenAI-compatible endpoint the agent already uses (LM Studio
by default), via ax-llm's ``OpenAICompatibleClient``.

This module is imported lazily and only when ``VA_AX_ROUTER=1``, so ``axllm`` is
never a hard dependency of the agent. If the ``ax`` extra is missing,
construction raises a clear error the caller logs and then falls back to the
native tool loop. Kept deliberately symmetric with ``dspy_router`` so the two can
be A/B compared through the eval harness (see ``services/eval/runner.py``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, Optional

from config import CONFIG

if TYPE_CHECKING:  # avoid importing the registry at module import time
    from tools.registry import ToolRegistry

log = logging.getLogger("voice-agent.ax_router")

# Where an optimized (few-shot) program is persisted (see scripts/optimize_ax_router.py).
_COMPILED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ax_router.json")

# Same routing guidance as dspy_router._build_signature, so the frameworks are
# compared on identical instructions rather than prompt wording.
_ROUTE_INSTRUCTION = (
    "Pick the single best tool to answer the user, or 'none' for plain chat. "
    "Only choose a tool when it is clearly needed to answer a real-world or "
    "factual question (time, date, weather, air quality, live info, memory, "
    "media control). For casual conversation or emotional talk, return 'none'. "
    "tool_name must be an exact tool name from the catalog, or 'none'. "
    "args_json must be a JSON object of arguments for the chosen tool, or '{}'."
)


def _make_client(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    transport: Any | None = None,
):
    """Build an ax-llm OpenAI-compatible client (defaults to the agent's LM)."""
    from axllm import OpenAICompatibleClient

    options: dict[str, Any] = {
        "model": model or CONFIG.llm.model or "local-model",
        "base_url": base_url or CONFIG.llm.base_url,
        "api_key": api_key or CONFIG.llm.api_key,
    }
    if transport is not None:  # offline tests inject a canned completion callable
        options["transport"] = transport
    return OpenAICompatibleClient(**options)


def _build_signature():
    from axllm import AxSignature

    return AxSignature(
        "utterance:string, tool_catalog:string -> tool_name:string, args_json:string",
        description=_ROUTE_INSTRUCTION,
    )


class AxRouter:
    """Wraps an ax-llm generator that maps an utterance to (tool_name, args)."""

    def __init__(self, *, client: Any | None = None) -> None:
        from axllm import AxGen  # raises ImportError if `ax` extra is missing

        self._client = client if client is not None else _make_client()
        self._gen = AxGen(_build_signature())
        # Load an optimized few-shot program if one has been compiled offline.
        if os.path.exists(_COMPILED_PATH):
            try:
                with open(_COMPILED_PATH, encoding="utf-8") as fh:
                    artifact = json.load(fh)
                demos = artifact.get("demos") if isinstance(artifact, dict) else artifact
                self._gen.set_demos(demos or [])
                log.info(
                    "Ax router loaded %d compiled demos from %s",
                    len(demos or []),
                    _COMPILED_PATH,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Ax router: could not load compiled program: %s", exc)

    def route(self, utterance: str, registry: "ToolRegistry") -> Optional[tuple[str, dict]]:
        """Return (tool_name, args) to execute, or None to defer to normal chat/tool loop."""
        utterance = (utterance or "").strip()
        if not utterance:
            return None
        catalog = registry.prompt_descriptions()
        try:
            pred = self._gen.forward(
                self._client,
                {"utterance": utterance, "tool_catalog": catalog},
            )
        except Exception as exc:  # noqa: BLE001 - never let routing crash a turn
            log.warning("Ax router prediction failed: %s", exc)
            return None

        name = str((pred or {}).get("tool_name", "") or "").strip()
        if not name or name.lower() == "none":
            return None
        if name not in registry.names():
            log.info("Ax router picked unknown tool %r — ignoring", name)
            return None
        raw = str((pred or {}).get("args_json", "") or "{}").strip()
        try:
            args = json.loads(raw)
            if not isinstance(args, dict):
                args = {}
        except (TypeError, ValueError):
            args = {}
        log.info("Ax router chose tool=%s args=%s", name, args)
        return name, args
