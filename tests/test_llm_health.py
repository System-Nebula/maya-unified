"""Tests for LLM connection health helpers."""

from services.llm.health import (
    _resolved_model,
    _supports_models_list,
    build_agent_capabilities,
    check_llm_health,
    llm_ready_from_health,
)


def test_resolved_model_litellm():
    reasoning = {
        "provider": "litellm",
        "model": "local-model",
        "litellm": {"model": "gemini/gemini-2.0-flash"},
    }
    assert _resolved_model(reasoning) == "gemini/gemini-2.0-flash"


def test_resolved_model_webllm():
    reasoning = {
        "provider": "webllm",
        "webllm": {"model_id": "Llama-3.1-8B"},
    }
    assert _resolved_model(reasoning) == "Llama-3.1-8B"


def test_supports_models_list():
    assert _supports_models_list({"provider": "lm_studio", "base_url": "http://localhost:1234/v1"})
    assert _supports_models_list(
        {
            "provider": "litellm",
            "base_url": "http://localhost:1234/v1",
            "litellm": {"mode": "proxy"},
        }
    )
    assert not _supports_models_list({"provider": "litellm", "litellm": {"mode": "sdk"}})
    assert not _supports_models_list({"provider": "webllm"})


def test_webllm_skipped():
    result = check_llm_health({"provider": "webllm", "webllm": {"model_id": "x"}})
    assert result["status"] == "skipped"
    assert "browser" in result["detail"].lower()
