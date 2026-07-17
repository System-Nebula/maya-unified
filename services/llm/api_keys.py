"""Resolve LiteLLM / reasoning API keys from settings UI, local store, or env fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path

from services.paths import DATA_DIR

PLACEHOLDER_API_KEYS = frozenset({"", "lm-studio", "vllm-local", "local-model"})

# model prefix -> env var (bootstrap only — settings UI wins when configured)
_MODEL_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("gemini/", "GEMINI_API_KEY"),
    ("openrouter/", "OPENROUTER_API_KEY"),
    ("anthropic/", "ANTHROPIC_API_KEY"),
    ("openai/", "OPENAI_API_KEY"),
    ("groq/", "GROQ_API_KEY"),
    ("xai/", "XAI_API_KEY"),
    ("mistral/", "MISTRAL_API_KEY"),
)

_FALLBACK_ENV_KEYS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "VA_LLM_API_KEY",
)

_runtime_keys: dict[str, str] = {}


def _cache_key(operator_id: str | None) -> str:
    return str(operator_id or "global")


def _secrets_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "reasoning_api_keys.json"


def _load_secrets_file() -> dict[str, str]:
    path = _secrets_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        text = str(val or "").strip()
        if text and not is_placeholder_api_key(text):
            out[str(key)] = text
    return out


def _write_secrets_file(data: dict[str, str]) -> None:
    path = _secrets_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_placeholder_api_key(key: str | None) -> bool:
    return (key or "").strip().lower() in PLACEHOLDER_API_KEYS


def litellm_model_from_reasoning(reasoning: dict) -> str:
    if str(reasoning.get("provider", "")).lower() == "litellm":
        litellm = reasoning.get("litellm") or {}
        return str(litellm.get("model") or reasoning.get("model") or "")
    return str(reasoning.get("model") or "")


def env_api_key_for_model(model: str) -> str:
    model_lc = (model or "").strip().lower()
    for prefix, env_name in _MODEL_ENV_KEYS:
        if model_lc.startswith(prefix):
            val = os.environ.get(env_name, "").strip()
            if val and not is_placeholder_api_key(val):
                return val
    for env_name in _FALLBACK_ENV_KEYS:
        val = os.environ.get(env_name, "").strip()
        if val and not is_placeholder_api_key(val):
            return val
    return ""


def load_persisted_reasoning_api_key(*, operator_id: str | None = None) -> str:
    return _load_secrets_file().get(_cache_key(operator_id), "").strip()


def persist_reasoning_api_key(api_key: str | None, *, operator_id: str | None = None) -> None:
    """Write API key from Settings UI to local data/ (gitignored), not settings.json."""
    key = (api_key or "").strip()
    slot = _cache_key(operator_id)
    secrets = _load_secrets_file()
    if is_placeholder_api_key(key):
        if slot in secrets:
            secrets.pop(slot, None)
            _write_secrets_file(secrets)
        return
    secrets[slot] = key
    _write_secrets_file(secrets)


def clear_persisted_reasoning_api_key(*, operator_id: str | None = None) -> None:
    persist_reasoning_api_key(None, operator_id=operator_id)


def stash_reasoning_api_key(api_key: str | None, *, operator_id: str | None = None) -> None:
    """Keep UI-entered keys in memory and on disk after redacting settings.json."""
    key = (api_key or "").strip()
    if is_placeholder_api_key(key):
        return
    persist_reasoning_api_key(key, operator_id=operator_id)
    _runtime_keys[_cache_key(operator_id)] = key


def clear_runtime_api_key(*, operator_id: str | None = None) -> None:
    _runtime_keys.pop(_cache_key(operator_id), None)


def apply_reasoning_api_key_patch(
    patch: dict | None,
    *,
    operator_id: str | None = None,
) -> None:
    """Apply api_key from a settings PATCH before merge/redact.

    Placeholders/masks are ignored (leave stored secret unchanged). Explicit
    clears are handled by ``sanitize_settings_patch`` via ``clear_api_key``.
    """
    if not isinstance(patch, dict):
        return
    reasoning = patch.get("reasoning")
    if not isinstance(reasoning, dict) or "api_key" not in reasoning:
        return
    key = str(reasoning.get("api_key") or "").strip()
    if is_placeholder_api_key(key):
        # Do not clear on placeholder — UI often re-posts the masked field.
        reasoning.pop("api_key", None)
        return
    stash_reasoning_api_key(key, operator_id=operator_id)


def resolve_reasoning_api_key(
    reasoning: dict | None,
    *,
    operator_id: str | None = None,
) -> str:
    """Effective key: settings value, then Settings UI store, then env bootstrap."""
    if not isinstance(reasoning, dict):
        reasoning = {}
    raw = str(reasoning.get("api_key") or "").strip()
    if not is_placeholder_api_key(raw):
        return raw

    cached = _runtime_keys.get(_cache_key(operator_id), "").strip()
    if cached:
        return cached

    persisted = load_persisted_reasoning_api_key(operator_id=operator_id)
    if persisted:
        return persisted

    if reasoning.get("api_key_configured"):
        return raw or "lm-studio"

    env_key = env_api_key_for_model(litellm_model_from_reasoning(reasoning))
    if env_key:
        return env_key

    return raw or "lm-studio"
