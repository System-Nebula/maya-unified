"""Offline optimizer for the DSPy tool router.

Compiles a few-shot program for `dspy_router.ToolRoute` from a handful of labeled
examples and saves it to `packages/voice-runtime/data/dspy_router.json`, which
`DspyRouter` loads automatically at startup. This is the growth path — add
examples over time to improve routing without touching agent code.

Run (with dspy installed and LM Studio up):
    steam-run .venv/bin/python scripts/optimize_dspy_router.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "packages", "voice-runtime"))

from dspy_router import _build_signature, _make_lm, _COMPILED_PATH  # noqa: E402


# (utterance, expected tool_name, expected args_json)
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


def _metric(example, pred, trace=None) -> float:
    return 1.0 if (getattr(pred, "tool_name", "") or "").strip() == example.tool_name else 0.0


def main() -> None:
    import dspy

    dspy.configure(lm=_make_lm())
    signature = _build_signature()
    student = dspy.Predict(signature)

    trainset = [
        dspy.Example(utterance=u, tool_catalog="(catalog injected at runtime)",
                     tool_name=name, args_json=args).with_inputs("utterance", "tool_catalog")
        for (u, name, args) in EXAMPLES
    ]

    optimizer = dspy.BootstrapFewShot(metric=_metric, max_bootstrapped_demos=4)
    compiled = optimizer.compile(student, trainset=trainset)

    os.makedirs(os.path.dirname(_COMPILED_PATH), exist_ok=True)
    compiled.save(_COMPILED_PATH)
    print(f"Saved compiled router to {_COMPILED_PATH}")


if __name__ == "__main__":
    main()
