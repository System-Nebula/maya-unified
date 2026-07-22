"""Offline optimizer for the Ax tool router.

The ax-llm counterpart to ``optimize_dspy_router.py``. Compiles a handful of
labeled examples into few-shot demos for ``ax_router.AxRouter`` and saves them to
``packages/voice-runtime/data/ax_router.json``, which the router loads
automatically at startup (via ``AxGen.set_demos``). This is the growth path — add
examples over time to improve routing without touching agent code.

Unlike the DSPy optimizer this needs no LLM endpoint: the demos are the labeled
pairs themselves (a fixed few-shot program), so it runs fully offline.

Run:
    steam-run .venv/bin/python scripts/optimize_ax_router.py
"""

from __future__ import annotations

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Same destination AxRouter reads at startup (ax_router._COMPILED_PATH); computed
# locally so this optimizer stays fully offline and free of runtime imports.
_COMPILED_PATH = os.path.join(_ROOT, "packages", "voice-runtime", "data", "ax_router.json")


# (utterance, expected tool_name, expected args_json) — shared corpus with
# optimize_dspy_router.EXAMPLES so both frameworks learn from the same labels.
EXAMPLES = [
    ("what day is it?", "get_current_datetime", "{}"),
    ("what time is it right now?", "get_current_datetime", "{}"),
    ("Hey Maya, what's today?", "get_current_datetime", "{}"),
    ("srry that date?", "get_current_datetime", "{}"),
    ("what's the air quality today?", "get_air_quality", "{}"),
    ("is the air safe in Seattle?", "get_air_quality", '{"location": "Seattle"}'),
    ("what's the weather tonight?", "weather", "{}"),
    ("what's the price of bitcoin today?", "web_search", '{"query": "Bitcoin price today"}'),
    ("how is Oracle stock?", "web_search", '{"query": "Oracle ORCL stock price today"}'),
    (
        "what is Olivia Rodrigo's latest album?",
        "web_search",
        '{"query": "Olivia Rodrigo latest album"}',
    ),
    ("hi maya, how are you?", "none", "{}"),
    ("i love you maya", "none", "{}"),
    ("play some jungle on discord", "none", "{}"),  # handled by other routers, not this one
]

# Placeholder catalog string in the demos; the real catalog is injected at
# runtime by AxRouter.route (matches optimize_dspy_router's convention).
_RUNTIME_CATALOG = "(catalog injected at runtime)"


def _build_demos() -> list[dict]:
    return [
        {
            "input": {"utterance": utterance, "tool_catalog": _RUNTIME_CATALOG},
            "output": {"tool_name": name, "args_json": args},
        }
        for (utterance, name, args) in EXAMPLES
    ]


def main() -> None:
    artifact = {"demos": _build_demos()}
    os.makedirs(os.path.dirname(_COMPILED_PATH), exist_ok=True)
    with open(_COMPILED_PATH, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2, ensure_ascii=False)
    print(f"Saved {len(artifact['demos'])} compiled demos to {_COMPILED_PATH}")


if __name__ == "__main__":
    main()
