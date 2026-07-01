"""LangGraph state for the research agent."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from maya_contracts import (
    FetchedPage,
    OperatorContext,
    PriorResearchRef,
    ResearchPlan,
    ResearchReport,
    SentimentBundle,
    SynthesisBundle,
    WebSearchResult,
)


class ResearchState(TypedDict, total=False):
    # input
    run_id: str
    brief: str
    depth: Literal["shallow", "deep"]
    source_mask: list[str]
    seed_urls: list[str]
    operator_id: str
    discord_thread_id: str | None
    prior_research_id: str | None

    # coordinator
    prior_research: list[PriorResearchRef]
    research_context: dict[str, Any]
    delta_mode: bool
    delta_since: str | None

    # planner
    plan: ResearchPlan | None
    plan_approved: bool

    # parallel results
    web_results: list[WebSearchResult]
    fetched_pages: list[FetchedPage]
    reddit_bundles: list[SentimentBundle]
    operator_context: OperatorContext | None
    graph_recall: list[dict[str, Any]]

    # synthesis
    synthesis: SynthesisBundle | None

    # output
    report: ResearchReport | None
    artifact_id: str | None
    artifact_key: str | None
    errors: list[str]
    progress: list[dict[str, Any]]
