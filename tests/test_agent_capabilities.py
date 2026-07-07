"""Tests for agent capability disclosure and chat routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
    assert partial["imagine"] is True

    full = build_agent_capabilities(voice_ready=True, health=health, imagine_ready=False)
    assert full["text_chat_enriched"] is True
    assert full["voice_session"] is True
    assert full["imagine"] is False


def test_status_poll_imagine_ready_when_cached_comfyui_ok(monkeypatch) -> None:
    from services.discovery.policy import imagine_capability_ready

    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("MAYA_FAKE_COMFY", raising=False)
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"}}
    cached_ok = {
        "status": "ok",
        "detail": "comfyui-api reachable at http://127.0.0.1:3030",
        "url": "http://127.0.0.1:3030",
    }

    with patch(
        "services.imagine.health.get_cached_comfyui_health",
        return_value=cached_ok,
    ):
        health = cached_ok
        imagine_ready = imagine_capability_ready(health, settings=settings)
        caps = build_agent_capabilities(True, {"status": "ok"}, imagine_ready=imagine_ready)

    assert health["status"] == "ok"
    assert health["detail"] != "Probe skipped"
    assert caps["imagine"] is True


def test_imagine_disabled_skips_comfy_health_in_hub() -> None:
    from services.discovery.policy import imagine_capability_ready
    from services.imagine.settings import get_imagine_settings

    settings = {"imagine": {"enabled": False, "comfyui_url": "http://127.0.0.1:3030"}}
    assert get_imagine_settings(settings)["enabled"] is False
    assert imagine_capability_ready(
        {"status": "error", "detail": "Cannot connect to http://127.0.0.1:3030"},
        settings=settings,
    ) is False

    hub_src = (ROOT / "services" / "voice" / "hub.py").read_text(encoding="utf-8")
    assert "imagine_enabled = bool(get_imagine_settings(settings).get(\"enabled\"))" in hub_src
    assert "if imagine_enabled:" in hub_src
    assert '"imagine_enabled": imagine_enabled' in hub_src

    conv_src = (ROOT / "apps" / "dashboard" / "conversation.html").read_text(encoding="utf-8")
    assert "imagineEnabled && $store.mayaShell?.capabilities?.imagine === false" in conv_src


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
