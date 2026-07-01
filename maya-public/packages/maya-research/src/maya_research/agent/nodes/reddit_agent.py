"""Reddit sentiment research node."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maya_contracts import SentimentBundle, SubTaskType
from maya_research.agent.state import ResearchState
from maya_research.config import load_config
from maya_research.storage.run_repository import append_progress
from maya_research.tasks.llm import LlmError, analyze_structured, llm_available
from maya_research.tools.reddit import RedditClient


class _SentimentSummary(BaseModel):
    sentiment_summary: str
    recurring_themes: list[str]
    notable_quotes: list[str]


async def reddit_agent_node(state: ResearchState) -> ResearchState:
    plan = state.get("plan")
    if not plan:
        return state
    cfg = load_config()
    client = RedditClient(cfg.reddit_user_agent)
    bundles: list[SentimentBundle] = list(state.get("reddit_bundles") or [])

    for task in plan.subtasks:
        if task.type != SubTaskType.REDDIT:
            continue
        subreddit = task.source_hint or "all"
        try:
            bundle = await client.build_sentiment_bundle(subreddit, task.query)
            if llm_available():
                bundle = await _maybe_enrich_bundle(bundle)
            bundles.append(bundle)
            if state.get("run_id"):
                await append_progress(
                    state["run_id"],
                    "reddit",
                    f"Sentiment complete ({subreddit}: {len(bundle.posts)} posts)",
                )
        except Exception as exc:
            errors = list(state.get("errors") or [])
            errors.append(f"reddit failed for {subreddit}: {exc}")
            state = {**state, "errors": errors}

    return {**state, "reddit_bundles": bundles}


async def _maybe_enrich_bundle(bundle: SentimentBundle) -> SentimentBundle:
    try:
        prompt = (
            f"Summarize Reddit sentiment for r/{bundle.subreddit} query '{bundle.query}'.\n"
            f"Posts: {[p.title for p in bundle.posts[:10]]}\n"
            "Return JSON: sentiment_summary, recurring_themes, notable_quotes."
        )
        out = await analyze_structured(prompt, _SentimentSummary)
        return bundle.model_copy(
            update={
                "sentiment_summary": out.sentiment_summary,
                "recurring_themes": out.recurring_themes or bundle.recurring_themes,
                "notable_quotes": out.notable_quotes or bundle.notable_quotes,
            }
        )
    except LlmError:
        return bundle
