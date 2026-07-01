"""Web research node — SearXNG two-pass search."""

from __future__ import annotations

from maya_contracts import SubTaskType, WebSearchResult
from maya_research.agent.state import ResearchState
from maya_research.config import load_config
from maya_research.storage.run_repository import append_progress
from maya_research.tools.searxng import SearxngClient


async def web_researcher_node(state: ResearchState) -> ResearchState:
    plan = state.get("plan")
    if not plan:
        return state
    cfg = load_config()
    client = SearxngClient(cfg.searxng_url)
    results: list[WebSearchResult] = list(state.get("web_results") or [])

    search_tasks = [s for s in plan.subtasks if s.type == SubTaskType.WEB_SEARCH]
    for task in search_tasks:
        try:
            batch = await client.two_pass_search(task.query)
            results.extend(batch)
            if state.get("run_id"):
                await append_progress(
                    state["run_id"],
                    "web_search",
                    f"Completed: {task.query[:80]}",
                    details={"count": len(batch)},
                )
        except Exception as exc:
            errors = list(state.get("errors") or [])
            errors.append(f"web_search failed: {exc}")
            state = {**state, "errors": errors}

    seen: set[str] = set()
    deduped: list[WebSearchResult] = []
    for r in results:
        if r.url in seen:
            continue
        seen.add(r.url)
        deduped.append(r)

    return {**state, "web_results": deduped}
