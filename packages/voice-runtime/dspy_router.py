"""Opt-in DSPy tool router for the voice agent.

A structured, optimizable alternative to the hand-rolled keyword/orchestrator
routing: given a user utterance and the live tool catalog, decide which tool (if
any) to call and with what arguments. It talks to the same local LM Studio
endpoint the agent already uses, via DSPy's LiteLLM backend.

This module is imported lazily and only when `VA_DSPY_ROUTER=1`, so `dspy` is
never a hard dependency of the agent. If `dspy` is missing, construction raises a
clear error the caller logs and then falls back to the native tool loop.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Optional

from config import CONFIG

if TYPE_CHECKING:  # avoid importing the registry at module import time
    from tools.registry import ToolRegistry

log = logging.getLogger("voice-agent.dspy_router")

# Where an optimized program is persisted (see scripts/optimize_dspy_router.py).
_COMPILED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dspy_router.json")


def _make_lm():
    import dspy

    model = CONFIG.llm.model or "local-model"
    return dspy.LM(
        f"openai/{model}",
        api_base=CONFIG.llm.base_url,
        api_key=CONFIG.llm.api_key,
        temperature=0.0,
        max_tokens=256,
    )


def _build_signature():
    import dspy

    class ToolRoute(dspy.Signature):
        """Pick the single best tool to answer the user, or 'none' for plain chat.

        Only choose a tool when it is clearly needed to answer a real-world or
        factual question (time, date, weather, air quality, live info, memory,
        media control). For casual conversation or emotional talk, return 'none'.
        args_json must be a JSON object of arguments for the chosen tool.
        """

        utterance: str = dspy.InputField(desc="What the user said.")
        tool_catalog: str = dspy.InputField(desc="Available tools, one per line: name — description.")
        tool_name: str = dspy.OutputField(desc="Exact tool name to call, or 'none'.")
        args_json: str = dspy.OutputField(desc="JSON object of arguments for the tool, or '{}'.")

    return ToolRoute


class DspyRouter:
    """Wraps a DSPy predictor that maps an utterance to (tool_name, args)."""

    def __init__(self) -> None:
        import dspy  # raises ImportError if not installed — caller handles it

        self._dspy = dspy
        self._lm = _make_lm()
        signature = _build_signature()
        self._predict = dspy.Predict(signature)
        # Load an optimized program if one has been compiled offline.
        if os.path.exists(_COMPILED_PATH):
            try:
                self._predict.load(_COMPILED_PATH)
                log.info("DSPy router loaded compiled program from %s", _COMPILED_PATH)
            except Exception as exc:  # noqa: BLE001
                log.warning("DSPy router: could not load compiled program: %s", exc)

    def route(self, utterance: str, registry: "ToolRegistry") -> Optional[tuple[str, dict]]:
        """Return (tool_name, args) to execute, or None to defer to normal chat/tool loop."""
        utterance = (utterance or "").strip()
        if not utterance:
            return None
        catalog = registry.prompt_descriptions()
        try:
            with self._dspy.context(lm=self._lm):
                pred = self._predict(utterance=utterance, tool_catalog=catalog)
        except Exception as exc:  # noqa: BLE001 - never let routing crash a turn
            log.warning("DSPy router prediction failed: %s", exc)
            return None

        name = (getattr(pred, "tool_name", "") or "").strip()
        if not name or name.lower() == "none":
            return None
        if name not in registry.names():
            log.info("DSPy router picked unknown tool %r — ignoring", name)
            return None
        raw = (getattr(pred, "args_json", "") or "{}").strip()
        try:
            args = json.loads(raw)
            if not isinstance(args, dict):
                args = {}
        except (TypeError, ValueError):
            args = {}
        log.info("DSPy router chose tool=%s args=%s", name, args)
        return name, args
