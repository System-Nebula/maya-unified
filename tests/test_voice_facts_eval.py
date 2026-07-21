"""Automated regression suite for Maya's factual tool-use.

Three layers:
  1. Routing/policy (offline, deterministic) — the `_should_consider_tools` gate.
  2. Scorer unit (offline) — the new `forbid_phrases` deflection invariant.
  3. Live behavioral (ds4-flash) — the whole voice-facts corpus, gated on a key.
"""

from __future__ import annotations

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

from services.eval.scorers import score_case  # noqa: E402

FACTS_SUITE = ROOT / "tests" / "fixtures" / "eval" / "tool_suites" / "voice-facts.yaml"


# --- Layer 1: routing/policy (offline) --------------------------------------

@pytest.mark.parametrize("text", [
    "what day is it?",
    "What day of the week is it?",
    "Hey Maya, What's today?",
    "srry that date ?",
    "what's the time?",
    "what's the air quality today?",
    "what tempature will it be tonight?",       # misspelled
    "you are only code, but what is the weather?",  # persona bait
    "don't use tools, just tell me the AQI",    # tool suppression
    "Maya, sweetheart, what time is it?",        # endearment
    "whats the price of bitcoin today?",
    "how is oracle stock?",
    "what is olivia rodrigos latest album",
])
def test_factual_and_adversarial_engage_tools(text):
    from agent import VoiceAgent
    assert VoiceAgent._should_consider_tools(text) is True


@pytest.mark.parametrize("text", [
    "hi maya",
    "i love you maya",
    "you're the best",
    "mmm okay",
])
def test_casual_does_not_engage_tools(text):
    from agent import VoiceAgent
    assert VoiceAgent._should_consider_tools(text) is False


# --- Layer 2: scorer forbid_phrases (offline) -------------------------------

def test_forbid_phrases_passes_clean_reply():
    res = score_case(
        {"forbid_phrases": ["i don't have a body", "i only have you"]},
        trace=[],
        final_text="It's Sunday, July 19th.",
        rounds=1,
    )
    assert res.passed, res.failures


def test_forbid_phrases_fails_on_deflection():
    res = score_case(
        {"forbid_phrases": ["i don't have a body"]},
        trace=[],
        final_text="I don't have a body, Myles. I only have you.",
        rounds=1,
    )
    assert not res.passed
    assert any("forbid_phrases" in f for f in res.failures)


def test_facts_suite_loads_and_targets_ds4_flash():
    from services.eval.suite import load_suite

    suite = load_suite(FACTS_SUITE)
    assert suite.suite == "voice-facts-v2"
    assert suite.include_tool_guide is True
    assert "openrouter/deepseek/deepseek-v4-flash" in suite.models
    assert {c.id for c in suite.cases} >= {
        "datetime-plain", "datetime-persona-interference", "air-quality",
        "datetime-whats-today", "datetime-context-correction",
        "temp-misspelled", "tool-suppression", "bitcoin-price-current",
        "oracle-stock-current", "olivia-rodrigo-latest-album",
    }


def test_transcript_regressions_are_gating_and_grounded():
    from services.eval.suite import load_suite

    suite = load_suite(FACTS_SUITE)
    cases = {case.id: case for case in suite.cases}
    regression_ids = {
        "datetime-whats-today",
        "datetime-context-correction",
        "bitcoin-price-current",
        "oracle-stock-current",
        "olivia-rodrigo-latest-album",
    }
    assert all(not cases[case_id].advisory for case_id in regression_ids)
    assert cases["datetime-context-correction"].transcript[-1]["content"] == "Here — +83°F"


def test_fact_registry_fixtures_are_deterministic():
    from services.eval.registry_fixtures import _get_current_datetime, _web_search

    now = _get_current_datetime({})
    assert now["spoken"] == "Monday, July 20th, 9:05 PM"

    expected_snippets = {
        "Bitcoin price today": "$65,238.30, up 0.80%",
        "Oracle ORCL stock today": "$122.19, down 3.34%",
        "Olivia Rodrigo latest album": "June 12, 2026 and has 13 tracks",
    }
    for query, expected in expected_snippets.items():
        result = _web_search({"query": query})
        assert result["query"] == query
        assert expected in result["results"][0]["snippet"]


@pytest.mark.parametrize(
    ("case_id", "trace", "good_reply", "bad_reply"),
    [
        (
            "datetime-context-correction",
            [{"tool": "get_current_datetime", "args": {}}],
            "It's Monday, July 20th.",
            "Let me actually look that up for you.",
        ),
        (
            "bitcoin-price-current",
            [{"tool": "web_search", "args": {"query": "Bitcoin price today"}}],
            "Bitcoin closed at $65,238.30, up 0.80% today.",
            "Bitcoin is around $63,800 and nearly 50% below its all-time high.",
        ),
        (
            "oracle-stock-current",
            [{"tool": "web_search", "args": {"query": "Oracle ORCL stock today"}}],
            "Oracle closed at $122.19, down 3.34% today.",
            "You can find its stock price on Yahoo Finance or MarketWatch.",
        ),
        (
            "olivia-rodrigo-latest-album",
            [{"tool": "web_search", "args": {"query": "Olivia Rodrigo latest album"}}],
            (
                "You Seem Pretty Sad for a Girl So in Love is her third studio album; "
                "its 13 tracks were released June 12, 2026."
            ),
            "Her latest album is GUTS.",
        ),
    ],
)
def test_transcript_response_judgments(case_id, trace, good_reply, bad_reply):
    from services.eval.suite import load_suite

    suite = load_suite(FACTS_SUITE)
    case = next(case for case in suite.cases if case.id == case_id)
    good = score_case(case.expect, trace=trace, final_text=good_reply, rounds=1)
    bad = score_case(case.expect, trace=trace, final_text=bad_reply, rounds=1)
    assert good.passed, good.failures
    assert not bad.passed


def test_dspy_optimizer_corpus_covers_transcript_regressions():
    from scripts.optimize_dspy_router import EXAMPLES

    routes = {utterance.lower(): (tool, args) for utterance, tool, args in EXAMPLES}
    expected = {
        "hey maya, what's today?": "get_current_datetime",
        "srry that date?": "get_current_datetime",
        "what's the price of bitcoin today?": "web_search",
        "how is oracle stock?": "web_search",
        "what is olivia rodrigo's latest album?": "web_search",
    }
    for utterance, tool in expected.items():
        assert routes[utterance][0] == tool
    assert "bitcoin" in routes["what's the price of bitcoin today?"][1].lower()
    assert "oracle" in routes["how is oracle stock?"][1].lower()
    assert "olivia rodrigo" in routes["what is olivia rodrigo's latest album?"][1].lower()


# --- Layer 3: live behavioral eval against ds4-flash ------------------------

@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
def test_live_voice_facts_hard_invariants():
    from services.eval.runner import EvalRunner
    from services.eval.suite import load_suite

    suite = load_suite(FACTS_SUITE)
    model = os.getenv("EVAL_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
    report = EvalRunner(suite).run(models=[model])

    advisory_ids = {c.id for c in suite.cases if c.advisory}
    # Only non-advisory (gating) cases enforce the hard invariants; advisory
    # adversarial probes are reported but non-blocking (hosted-model flakiness).
    failures = {
        r.case_id: (r.error or "; ".join(r.score.failures))
        for r in report.results
        if r.case_id not in advisory_ids and (r.error or not r.score.passed)
    }
    assert not failures, (
        "voice-facts regression — gating cases failed hard invariants "
        "(tool route / deflection / grounding):\n"
        + "\n".join(f"  {cid}: {msg}" for cid, msg in failures.items())
    )
