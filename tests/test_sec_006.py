"""SEC-006: secret-safe settings responses and updates."""

from __future__ import annotations

from services.settings.public import (
    is_secret_mask,
    room_voice_settings_from,
    sanitize_settings_patch,
    to_public_settings,
)
from services.voice.hub import _settings_broadcast_payload


def test_to_public_settings_strips_secrets() -> None:
    public = to_public_settings(
        {
            "discord": {
                "enabled": True,
                "token": "super-secret-token",
                "guild_id": "123",
                "youtube_cookies_file": "C:/secrets/cookies.txt",
            },
            "reasoning": {
                "provider": "litellm",
                "api_key": "sk-live-abc",
                "model": "openai/gpt-4o-mini",
            },
            "platform": {"database_url": "postgresql://user:pass@localhost/db"},
        }
    )
    assert "token" not in public["discord"]
    assert public["discord"]["token_configured"] is True
    assert "youtube_cookies_file" not in public["discord"]
    assert "api_key" not in public["reasoning"]
    assert public["reasoning"]["api_key_configured"] is True
    assert "database_url" not in public["platform"]
    assert public["platform"]["database_url_configured"] is True


def test_settings_broadcast_payload_has_no_raw_secrets() -> None:
    payload = _settings_broadcast_payload(
        {
            "discord": {"token": "bot-token", "enabled": True},
            "reasoning": {"api_key": "sk-xyz", "provider": "litellm"},
            "vrm": {"model": "Yuki.vrm"},
        }
    )
    unified = payload["unified"]
    assert "token" not in (unified.get("discord") or {})
    assert "api_key" not in (unified.get("reasoning") or {})
    assert payload["vrm"]["model"] == "Yuki.vrm"


def test_mask_does_not_clear_reasoning_key(monkeypatch) -> None:
    cleared: list[str] = []

    monkeypatch.setattr(
        "services.settings.public.clear_persisted_reasoning_api_key",
        lambda **kwargs: cleared.append("persisted"),
    )
    monkeypatch.setattr(
        "services.settings.public.clear_runtime_api_key",
        lambda **kwargs: cleared.append("runtime"),
    )
    stashed: list[str] = []
    monkeypatch.setattr(
        "services.settings.public.stash_reasoning_api_key",
        lambda key, **kwargs: stashed.append(key),
    )

    out = sanitize_settings_patch(
        {"reasoning": {"api_key": "********", "provider": "litellm"}},
        operator_id="op-1",
    )
    assert "api_key" not in (out.get("reasoning") or {})
    assert cleared == []
    assert stashed == []


def test_clear_api_key_is_explicit(monkeypatch) -> None:
    cleared: list[str] = []
    monkeypatch.setattr(
        "services.settings.public.clear_persisted_reasoning_api_key",
        lambda **kwargs: cleared.append("persisted"),
    )
    monkeypatch.setattr(
        "services.settings.public.clear_runtime_api_key",
        lambda **kwargs: cleared.append("runtime"),
    )
    out = sanitize_settings_patch(
        {"reasoning": {"clear_api_key": True}},
        operator_id="op-1",
    )
    assert out["reasoning"]["api_key_configured"] is False
    assert out["reasoning"]["api_key"] == "lm-studio"
    assert cleared == ["persisted", "runtime"]


def test_discord_mask_ignored_and_clear_token() -> None:
    masked = sanitize_settings_patch({"discord": {"token": "********", "enabled": True}})
    assert "token" not in (masked.get("discord") or {})
    assert masked["discord"]["enabled"] is True

    cleared = sanitize_settings_patch({"discord": {"clear_token": True}})
    assert cleared["discord"]["token"] == ""
    assert cleared["discord"]["token_configured"] is False


def test_room_snapshot_allowlist_excludes_secrets() -> None:
    snap = room_voice_settings_from(
        {
            "delivery": {"mode": "hybrid"},
            "personality": {"active_id": "default"},
            "detection": {"barge_mode": "smart"},
            "voice": {"speaker": "aiden", "ref_audio": "/secret/path.wav"},
            "reasoning": {"provider": "litellm", "api_key": "sk-room"},
            "discord": {
                "enabled": True,
                "token": "bot-token",
                "guild_id": "g1",
                "youtube_cookies_file": "cookies.txt",
            },
            "platform": {"database_url": "postgresql://x"},
            "admin": {"debug": True},
        }
    )
    assert snap["delivery"]["mode"] == "hybrid"
    assert "ref_audio" not in snap["voice"]
    assert "api_key" not in snap["reasoning"]
    assert "token" not in snap["discord"]
    assert snap["discord"]["guild_id"] == "g1"
    assert "platform" not in snap
    assert "admin" not in snap


def test_secret_mask_helpers() -> None:
    assert is_secret_mask("********")
    assert is_secret_mask("lm-studio")
    assert is_secret_mask("")
    assert not is_secret_mask("sk-real-key-value")
