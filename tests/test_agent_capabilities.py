"""Tests for agent capability disclosure and chat routing."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from services.llm.health import build_agent_capabilities, llm_ready_from_health


def test_llm_ready_from_health():
    assert llm_ready_from_health({"status": "ok"})
    assert llm_ready_from_health({"status": "warn"})
    assert not llm_ready_from_health({"status": "error"})
    assert not llm_ready_from_health({"status": "skipped"})


def test_build_agent_capabilities_progressive():
    health = {"status": "ok"}
    partial = build_agent_capabilities(voice_ready=False, health=health)
    assert partial["text_chat"] is True
    assert partial["text_chat_enriched"] is False
    assert partial["voice_session"] is False
    assert partial["tts_preview"] is False
    assert partial["eq_live"] is False
    assert partial["tools"] is False

    full = build_agent_capabilities(voice_ready=True, health=health)
    assert full["text_chat_enriched"] is True
    assert full["voice_session"] is True


def test_hub_chat_text_delegates_to_basic_when_not_ready():
    hub_src = (ROOT / "services" / "voice" / "hub.py").read_text(encoding="utf-8")
    assert "_chat_text_basic" in hub_src
    assert "return self._chat_text_basic" in hub_src


def test_maya_conversation_removed_demo_turn():
    path = "apps/dashboard/js/mayaConversation.js"
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "/api/voice/turn" not in content
    assert "Demo mode" not in content
    assert "/api/voice/agent/chat" in content
