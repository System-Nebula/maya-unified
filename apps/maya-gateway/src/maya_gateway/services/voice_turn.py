"""Conversational voice pipeline — the reasoning step.

Pipeline:

    listen (browser detection engine) -> transcript
        -> [this service] clean transcript -> parse intent -> compose reply
        -> Maya's conversational turn

The reply generation here is **self-contained and deterministic** so the
pipeline runs end-to-end with no external API keys. The ``_reason`` seam is
where a real reasoning model (OpenAI-compatible, set ``LLM_API_KEY``) would be
swapped in; the deterministic path doubles as a reliable offline fallback.
"""

from __future__ import annotations

import re
import time

from maya_contracts import (
    OperatorVoiceSettings,
    TurnIntent,
    TurnRole,
    VoiceTurnRequest,
    VoiceTurnResponse,
)

_FILLERS = {"um", "uh", "erm", "like", "you know", "uhh", "umm"}

_GREETING_WORDS = {"hi", "hello", "hey", "yo", "morning", "evening", "sup"}
_FAREWELL_WORDS = {"bye", "goodbye", "later", "cya", "goodnight", "night"}
_COMMAND_VERBS = {
    "play", "stop", "pause", "open", "close", "start", "show", "find",
    "search", "generate", "make", "create", "set", "mute", "unmute", "skip",
}

_QUESTION_WORDS = {
    "what", "why", "how", "when", "where", "who", "which", "can",
    "could", "would", "should", "do", "does", "is", "are", "will",
}


def _lead_word(text: str) -> str:
    """Leading alphabetic run, lowercased (so "What's" -> "what")."""
    m = re.match(r"[a-z]+", text.strip().lower())
    return m.group(0) if m else ""


def clean_transcript(text: str, settings: OperatorVoiceSettings) -> str:
    """Apply Wispr-Flow-style cleanup: trim, drop fillers, punctuate."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""

    if settings.filler_removal:
        tokens = [t for t in cleaned.split(" ") if t.lower().strip(",.!?") not in _FILLERS]
        cleaned = " ".join(tokens).strip()

    if not cleaned:
        return ""

    if settings.auto_punctuation:
        cleaned = cleaned[0].upper() + cleaned[1:]
        if cleaned[-1] not in ".?!":
            is_question = _lead_word(cleaned) in _QUESTION_WORDS
            cleaned += "?" if is_question else "."
    return cleaned


def parse_intent(text: str) -> TurnIntent:
    """Coarse rule-based intent classification."""
    stripped = text.strip().lower()
    if not stripped:
        return TurnIntent.EMPTY

    first = _lead_word(stripped)
    if first in _GREETING_WORDS:
        return TurnIntent.GREETING
    if first in _FAREWELL_WORDS:
        return TurnIntent.FAREWELL
    if first in _COMMAND_VERBS:
        return TurnIntent.COMMAND
    if stripped.endswith("?") or first in _QUESTION_WORDS:
        return TurnIntent.QUESTION
    return TurnIntent.STATEMENT


def _reason(transcript: str, intent: TurnIntent, settings: OperatorVoiceSettings) -> str:
    """Compose Maya's conversational turn for the parsed intent.

    Deterministic persona-flavoured responder. Replace the body with a call to
    an OpenAI-compatible reasoning model (``settings.reasoning_model``) to go
    fully generative; the contract (transcript+intent in, reply text out) stays
    the same.
    """
    persona = (settings.persona or "maya").strip().lower()
    name = "Maya" if persona == "maya" else persona.capitalize()

    if intent is TurnIntent.EMPTY:
        return f"I didn't catch anything that time — go ahead, I'm listening."
    if intent is TurnIntent.GREETING:
        return f"Hey! {name} here. What are we working on?"
    if intent is TurnIntent.FAREWELL:
        return "Catch you later — I'll keep the session warm."
    if intent is TurnIntent.COMMAND:
        action = transcript.rstrip(".!?")
        return f'On it — "{action}". Want me to confirm before I run anything?'
    if intent is TurnIntent.QUESTION:
        topic = transcript.rstrip("?").strip()
        return f'Good question about "{topic}". Here\'s my quick take, then I can go deeper.'
    return f'Got it: "{transcript.rstrip(".")}" — noted. Anything you want me to do with that?'


def generate_turn(req: VoiceTurnRequest) -> VoiceTurnResponse:
    """Run the full reasoning step of the voice pipeline."""
    start = time.perf_counter()
    settings = req.settings or OperatorVoiceSettings()

    trace: list[str] = [
        f"listen: received transcript ({len(req.transcript)} chars) "
        f"via {settings.detection_mode.value} detection",
    ]

    cleaned = clean_transcript(req.transcript, settings)
    trace.append(
        f"transcribe/clean: wispr_model={settings.wispr_model} "
        f"lang={settings.language} -> {cleaned!r}"
    )

    intent = parse_intent(cleaned)
    trace.append(f"parse: intent={intent.value}")

    if req.history:
        trace.append(f"context: {len(req.history)} prior turn(s) considered")

    maya_turn = _reason(cleaned, intent, settings)
    trace.append(f"reason: {settings.reasoning_model} composed Maya's turn")

    latency_ms = (time.perf_counter() - start) * 1000.0
    return VoiceTurnResponse(
        transcript_raw=req.transcript,
        transcript_clean=cleaned,
        intent=intent,
        maya_turn=maya_turn,
        reasoning_model=settings.reasoning_model,
        reasoning_trace=trace,
        latency_ms=round(latency_ms, 3),
    )
