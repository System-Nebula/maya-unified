"""Tests for the voice conversational pipeline (service + routes)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from maya_contracts import (
    OperatorVoiceSettings,
    TurnIntent,
    VoiceTurnRequest,
)

from maya_gateway.main import app
from maya_gateway.services.voice_turn import (
    clean_transcript,
    generate_turn,
    parse_intent,
)

client = TestClient(app)


def test_clean_transcript_removes_fillers_and_punctuates():
    s = OperatorVoiceSettings()
    out = clean_transcript("um hey   uh   maya", s)
    assert "um" not in out.lower().split()
    assert out.endswith(".") or out.endswith("?")
    assert out[0].isupper()


def test_clean_transcript_question_mark():
    s = OperatorVoiceSettings()
    assert clean_transcript("what is the plan", s).endswith("?")


def test_clean_transcript_respects_disabled_flags():
    s = OperatorVoiceSettings(auto_punctuation=False, filler_removal=False)
    assert clean_transcript("um hello", s) == "um hello"


def test_parse_intent_variants():
    assert parse_intent("hey there") is TurnIntent.GREETING
    assert parse_intent("what time is it?") is TurnIntent.QUESTION
    assert parse_intent("play some music") is TurnIntent.COMMAND
    assert parse_intent("goodbye") is TurnIntent.FAREWELL
    assert parse_intent("the sky is blue") is TurnIntent.STATEMENT
    assert parse_intent("") is TurnIntent.EMPTY


def test_generate_turn_full_pipeline():
    resp = generate_turn(VoiceTurnRequest(transcript="um hey maya"))
    assert resp.intent is TurnIntent.GREETING
    assert resp.maya_turn
    assert resp.reasoning_trace  # listen -> clean -> parse -> reason
    assert resp.transcript_clean.lower().startswith("hey")
    assert resp.latency_ms >= 0


def test_route_defaults():
    r = client.get("/api/voice/settings/defaults")
    assert r.status_code == 200
    body = r.json()
    assert "vad" in body["detection_modes"]
    assert body["wispr_models"]
    assert body["default_settings"]["reasoning_model"]


def test_route_turn_roundtrip():
    r = client.post("/api/voice/turn", json={"transcript": "play the new album"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "command"
    assert body["maya_turn"]
    assert isinstance(body["reasoning_trace"], list)


def test_route_turn_with_settings_and_history():
    payload = {
        "transcript": "what's the plan",
        "settings": OperatorVoiceSettings(persona="maya").model_dump(),
        "history": [{"role": "operator", "text": "hi"}, {"role": "maya", "text": "Hey!"}],
    }
    r = client.post("/api/voice/turn", json=payload)
    assert r.status_code == 200
    assert r.json()["intent"] == "question"
