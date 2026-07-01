"""Page fetch node — crawl URLs from search results and seeds."""

from __future__ import annotations

from maya_contracts import SubTaskType
from maya_research.agent.state import ResearchState
from maya_research.storage.run_repository import append_progress
from maya_research.tools.page_fetcher import PageFetcher


async def page_fetcher_node(state: ResearchState) -> ResearchState:
    plan = state.get("plan")
    fetcher = PageFetcher()
    operator_urls: set[str] = set()
    ctx = state.get("operator_context")
    if ctx is not None and hasattr(ctx, "items"):
        operator_urls = {i.url for i in ctx.items}

    urls = list(state.get("seed_urls") or [])
    if plan:
        urls.extend(
            s.source_hint or s.query
            for s in plan.subtasks
            if s.type == SubTaskType.PAGE_FETCH
        )
    web_results = state.get("web_results") or []
    pages = list(state.get("fetched_pages") or [])
    try:
        pages.extend(
            await fetcher.fetch_from_search_results(web_results, operator_urls=operator_urls)
        )
        if urls:
            pages.extend(await fetcher.fetch_urls(urls, operator_urls=operator_urls))
        if state.get("run_id"):
            await append_progress(
                state["run_id"],
                "page_fetch",
                f"Fetched {len(pages)} pages",
            )
    except Exception as exc:
        errors = list(state.get("errors") or [])
        errors.append(f"page_fetch failed: {exc}")
        state = {**state, "errors": errors}

    seen: set[str] = set()
    deduped = []
    for p in pages:
        if p.url in seen:
            continue
        seen.add(p.url)
        deduped.append(p)
    return {**state, "fetched_pages": deduped}
