"""Tests for imagine settings schema, migration, and legacy fallback."""

from __future__ import annotations

from services.imagine.settings import (
    DEFAULT_IMAGINE_URL,
    get_imagine_settings,
    migrate_imagine_settings,
)


def test_get_imagine_settings_prefers_imagine_section() -> None:
    settings = {
        "imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"},
        "discord": {"imagine_enabled": False, "comfyui_url": "http://legacy:3000"},
    }
    out = get_imagine_settings(settings)
    assert out["enabled"] is True
    assert out["comfyui_url"] == "http://127.0.0.1:3030"


def test_get_imagine_settings_falls_back_to_discord_legacy() -> None:
    settings = {
        "discord": {"imagine_enabled": True, "comfyui_url": "http://legacy:3000/"},
    }
    out = get_imagine_settings(settings)
    assert out["enabled"] is True
    assert out["comfyui_url"] == "http://legacy:3000"


def test_get_imagine_settings_default_url() -> None:
    assert get_imagine_settings({})["comfyui_url"] == DEFAULT_IMAGINE_URL
    assert get_imagine_settings({})["enabled"] is False


def test_migrate_imagine_settings_from_discord() -> None:
    settings = {
        "discord": {"imagine_enabled": True, "comfyui_url": "http://legacy:3030"},
    }
    out = migrate_imagine_settings(settings)
    assert out["imagine"]["enabled"] is True
    assert out["imagine"]["comfyui_url"] == "http://legacy:3030"
    assert out["discord"]["imagine_enabled"] is True


def test_migrate_imagine_settings_does_not_overwrite_imagine() -> None:
    settings = {
        "imagine": {"enabled": False, "comfyui_url": "http://new:3030"},
        "discord": {"imagine_enabled": True, "comfyui_url": "http://legacy:3000"},
    }
    out = migrate_imagine_settings(settings)
    assert out["imagine"]["enabled"] is False
    assert out["imagine"]["comfyui_url"] == "http://new:3030"
