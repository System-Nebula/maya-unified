"""Tests for imagine settings schema, migration, and legacy fallback."""

from __future__ import annotations

from services.imagine.settings import (
    DEFAULT_IMAGINE_MODEL,
    DEFAULT_IMAGINE_URL,
    DEFAULT_REMARK_VISION_MODEL,
    get_imagine_settings,
    migrate_imagine_settings,
    resolve_imagine_default_model,
    resolve_imagine_model,
)


def test_get_imagine_settings_prefers_imagine_section() -> None:
    settings = {
        "imagine": {
            "enabled": True,
            "comfyui_url": "http://127.0.0.1:3030",
            "default_model": "krea2",
        },
        "discord": {"imagine_enabled": False, "comfyui_url": "http://legacy:3000"},
    }
    out = get_imagine_settings(settings)
    assert out["enabled"] is True
    assert out["comfyui_url"] == "http://127.0.0.1:3030"
    assert out["default_model"] == "krea2"


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
    assert get_imagine_settings({})["default_model"] == DEFAULT_IMAGINE_MODEL


def test_get_imagine_settings_invalid_default_model_falls_back() -> None:
    out = get_imagine_settings({"imagine": {"default_model": "not-a-model"}})
    assert out["default_model"] == DEFAULT_IMAGINE_MODEL


def test_resolve_imagine_default_model_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MAYA_IMAGINE_DEFAULT_MODEL", "krea2")
    assert resolve_imagine_default_model({"imagine": {"default_model": "zit"}}) == "krea2"


def test_resolve_imagine_model_explicit_overrides_default() -> None:
    settings = {"imagine": {"default_model": "krea2"}}
    assert resolve_imagine_model("zit", settings) == "zit"
    assert resolve_imagine_model(None, settings) == "krea2"
    assert resolve_imagine_model("", settings) == "krea2"


def test_migrate_imagine_settings_sets_default_model() -> None:
    out = migrate_imagine_settings({})
    assert out["imagine"]["default_model"] == DEFAULT_IMAGINE_MODEL
    assert out["imagine"]["remark_vision_model"] == DEFAULT_REMARK_VISION_MODEL


def test_schema_default_remark_vision_model_is_minimax() -> None:
    from services.settings.schema import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["imagine"]["remark_vision_model"] == DEFAULT_REMARK_VISION_MODEL


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
