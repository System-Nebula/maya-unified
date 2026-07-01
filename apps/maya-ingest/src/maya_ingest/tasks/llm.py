"""LLM structured analysis backend."""

from __future__ import annotations

import json
from typing import TypeVar

import httpx
from pydantic import BaseModel

from maya_ingest.config import load_config

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    pass


async def analyze_structured(
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
) -> T:
    """Call an OpenAI-compatible chat API and parse JSON into schema."""
    cfg = load_config()
    if not cfg.llm_api_key:
        raise LlmError("LLM_API_KEY not configured")

    base = cfg.llm_base_url.rstrip("/")
    model = cfg.llm_model
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {cfg.llm_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
        if resp.status_code >= 400:
            raise LlmError(f"LLM API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmError(f"LLM returned non-JSON: {content[:200]}") from exc
    return schema.model_validate(parsed)


def llm_available() -> bool:
    cfg = load_config()
    return bool(cfg.llm_api_key and cfg.llm_enabled)
