"""API key resolution for LiteLLM reasoning profile."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.llm.api_keys import (
    clear_persisted_reasoning_api_key,
    clear_runtime_api_key,
    env_api_key_for_model,
    is_placeholder_api_key,
    load_persisted_reasoning_api_key,
    persist_reasoning_api_key,
    resolve_reasoning_api_key,
    stash_reasoning_api_key,
)
from services.llm import api_keys as api_keys_mod


@pytest.fixture(autouse=True)
def _reset_api_key_state(tmp_path, monkeypatch):
    monkeypatch.setattr(api_keys_mod, "DATA_DIR", tmp_path)
    clear_runtime_api_key()
    clear_persisted_reasoning_api_key()
    yield
    clear_runtime_api_key()
    clear_persisted_reasoning_api_key()


def test_is_placeholder():
    assert is_placeholder_api_key("lm-studio")
    assert is_placeholder_api_key("")
    assert not is_placeholder_api_key("sk-test-key")


def test_stash_and_resolve(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reasoning = {"provider": "litellm", "api_key": "lm-studio", "litellm": {"model": "gemini/gemini-2.0-flash"}}
    stash_reasoning_api_key("AIzaSy_test_key", operator_id=None)
    assert resolve_reasoning_api_key(reasoning) == "AIzaSy_test_key"
    assert load_persisted_reasoning_api_key() == "AIzaSy_test_key"


def test_persist_survives_restart(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    clear_runtime_api_key()
    persist_reasoning_api_key("AIzaSy_persisted", operator_id=None)
    reasoning = {
        "provider": "litellm",
        "api_key": "lm-studio",
        "api_key_configured": True,
        "litellm": {"mode": "sdk", "model": "gemini/gemini-2.0-flash"},
    }
    assert resolve_reasoning_api_key(reasoning) == "AIzaSy_persisted"


def test_settings_ui_wins_over_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")
    persist_reasoning_api_key("AIzaSy_from_settings", operator_id=None)
    reasoning = {
        "provider": "litellm",
        "api_key": "lm-studio",
        "api_key_configured": True,
        "litellm": {"mode": "sdk", "model": "gemini/gemini-2.0-flash"},
    }
    assert resolve_reasoning_api_key(reasoning) == "AIzaSy_from_settings"


def test_resolve_from_env_when_not_configured(monkeypatch):
    clear_persisted_reasoning_api_key()
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")
    reasoning = {
        "provider": "litellm",
        "api_key": "lm-studio",
        "litellm": {"mode": "sdk", "model": "gemini/gemini-2.0-flash"},
    }
    assert resolve_reasoning_api_key(reasoning) == "env-gemini-key"


def test_env_api_key_for_model_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert env_api_key_for_model("openrouter/deepseek/deepseek-v4-flash") == "sk-or-test"
