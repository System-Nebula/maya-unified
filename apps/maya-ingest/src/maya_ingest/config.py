"""Env-driven config. No secrets or per-creator data in this file."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IngestConfig:
    youtube_api_key: str | None
    nomic_api_key: str | None
    embed_backend: str  # "nomic" | "local"
    face_match_enabled: bool
    github_token: str | None
    llm_backend: str
    llm_api_key: str | None
    llm_model: str
    llm_base_url: str
    llm_enabled: bool


def load_config() -> IngestConfig:
    llm_enabled = os.getenv("LLM_ENABLED", "true").lower() == "true"
    return IngestConfig(
        youtube_api_key=os.getenv("YOUTUBE_API_KEY"),
        nomic_api_key=os.getenv("NOMIC_API_KEY"),
        embed_backend=os.getenv("EMBED_BACKEND", "local"),
        face_match_enabled=os.getenv("FACE_MATCH_ENABLED", "false").lower() == "true",
        github_token=os.getenv("GITHUB_TOKEN"),
        llm_backend=os.getenv("LLM_BACKEND", "openai"),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_enabled=llm_enabled,
    )
