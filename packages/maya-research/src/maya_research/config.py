"""Env-driven research agent configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchConfig:
    searxng_url: str
    reddit_user_agent: str
    llm_api_key: str | None
    llm_model: str
    llm_base_url: str
    llm_enabled: bool
    embed_backend: str
    artifact_store: str
    artifact_store_dir: str
    seaweedfs_url: str
    ontology_dsn: str | None
    operator_history_boost: float
    prior_art_threshold: float
    page_fetch_min_credibility: float
    max_pages_per_run: int


def load_config() -> ResearchConfig:
    return ResearchConfig(
        searxng_url=os.getenv("RESEARCH_SEARXNG_URL", "http://localhost:8080/search").rstrip("/"),
        reddit_user_agent=os.getenv(
            "RESEARCH_REDDIT_USER_AGENT",
            "maya-research/0.1 (public research agent)",
        ),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        llm_enabled=os.getenv("LLM_ENABLED", "true").lower() == "true",
        embed_backend=os.getenv("EMBED_BACKEND", "local"),
        artifact_store=os.getenv("ARTIFACT_STORE", "local").lower(),
        artifact_store_dir=os.getenv(
            "ARTIFACT_STORE_DIR",
            "/tmp/maya-research-artifacts",
        ),
        seaweedfs_url=os.getenv("SEAWEEDFS_URL", "").rstrip("/"),
        ontology_dsn=os.getenv("MAYA_ONTOLOGY_DSN"),
        operator_history_boost=float(os.getenv("RESEARCH_OPERATOR_HISTORY_BOOST", "0.15")),
        prior_art_threshold=float(os.getenv("RESEARCH_PRIOR_ART_THRESHOLD", "0.3")),
        page_fetch_min_credibility=float(
            os.getenv("RESEARCH_PAGE_FETCH_MIN_CREDIBILITY", "0.35")
        ),
        max_pages_per_run=int(os.getenv("RESEARCH_MAX_PAGES_PER_RUN", "12")),
    )
