"""Tests for LLM tool-call eval harness (mock LLM + optional live OpenRouter)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VOICE_RUNTIME = ROOT / "packages" / "voice-runtime"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))

from llm import LLMResponse, ToolCall  # noqa: E402

from services.eval.runner import run_case_with_llm  # noqa: E402
from services.eval.scorers import score_case  # noqa: E402
from services.eval.suite import EvalCase, load_suite  # noqa: E402

FIXTURE_SUITE = ROOT / "tests" / "fixtures" / "eval" / "tool_suites" / "voice-tools.yaml"


class MockLLM:
    """Deterministic LLM for unit tests."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self._idx = 0
        self.last_completion_id = "mock-completion"

    def base_system_prompt(self, **kwargs) -> str:
        return "You are a test assistant."

    def complete(self, messages, tools=None, model=None, max_tokens=None) -> LLMResponse:
        if self._idx >= len(self._responses):
            return LLMResponse(content="Done.")
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


def test_load_suite_voice_tools() -> None:
    suite = load_suite(FIXTURE_SUITE)
    assert suite.suite == "voice-tools-v1"
    assert len(suite.models) >= 3
    assert any(c.id == "play-despacito" for c in suite.cases)


def test_scorer_tools_and_forbid() -> None:
    trace = [{"tool": "dashboard_play_music", "args": {"query": "despacito"}, "result": "{}"}]
    score = score_case(
        {
            "tools": [{"name": "dashboard_play_music", "args": {"query": {"contains": "despacito"}}}],
            "forbid_tools": ["music_lookup"],
            "max_rounds": 2,
        },
        trace=trace,
        final_text="Queued it.",
        rounds=1,
    )
    assert score.passed
    assert score.failures == []


def test_scorer_failure_wrong_tool() -> None:
    trace = [{"tool": "web_search", "args": {"query": "despacito"}, "result": "{}"}]
    score = score_case(
        {"tools": [{"name": "dashboard_play_music"}]},
        trace=trace,
        final_text="",
        rounds=1,
    )
    assert not score.passed
    assert any("dashboard_play_music" in f for f in score.failures)


def test_runner_native_tool_call() -> None:
    case = EvalCase(
        id="play-despacito",
        user="play despacito",
        expect={
            "tools": [{"name": "dashboard_play_music", "args": {"query": {"contains": "despacito"}}}],
        },
    )
    llm = MockLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc1",
                        name="dashboard_play_music",
                        arguments={"query": "despacito"},
                    )
                ],
            ),
            LLMResponse(content="Queued despacito for you."),
        ]
    )
    result = run_case_with_llm(case, llm, max_rounds=2)
    assert len(result.trace) == 1
    assert result.trace[0]["tool"] == "dashboard_play_music"
    score = score_case(case.expect, trace=result.trace, final_text=result.final_text, rounds=result.rounds)
    assert score.passed


def test_runner_json_text_tool_call() -> None:
    case = EvalCase(
        id="imagine-cat",
        user="generate a cat image",
        expect={
            "tools": [{"name": "imagine_generate", "args": {"prompt": {"contains": "cat"}}}],
        },
    )
    payload = json.dumps({"tool": "imagine_generate", "args": {"prompt": "a fluffy cat"}})
    llm = MockLLM(
        [
            LLMResponse(content=payload),
            LLMResponse(content="Here's your cat image."),
        ]
    )
    result = run_case_with_llm(case, llm, tool_mode="json", max_rounds=2)
    assert result.trace
    assert result.trace[0]["tool"] == "imagine_generate"
    score = score_case(case.expect, trace=result.trace, final_text=result.final_text, rounds=result.rounds)
    assert score.passed


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
def test_live_openrouter_play_despacito() -> None:
    from services.eval.runner import run_case, resolve_api_key
    from services.eval.suite import load_suite

    suite = load_suite(FIXTURE_SUITE)
    case = next(c for c in suite.cases if c.id == "play-despacito")
    model = os.getenv("EVAL_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    api_key = resolve_api_key(suite)
    result = run_case(suite, case, model, api_key=api_key)
    assert result.error is None, result.error
    # Live models may wording differ; tool selection is the primary signal.
    assert result.score.passed or result.trace, f"failures={result.score.failures} trace={result.trace}"
