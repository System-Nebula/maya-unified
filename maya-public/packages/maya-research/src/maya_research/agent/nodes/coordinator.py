"""Coordinator node — parse brief, recall prior art, set delta mode."""

from __future__ import annotations

from maya_research.agent.state import ResearchState
from maya_research.config import load_config
from maya_research.storage.graph_memory import (
    find_prior_research,
    load_graph_recall,
    should_use_delta_mode,
)
from maya_research.storage.run_repository import append_progress


async def coordinator_node(state: ResearchState) -> ResearchState:
    cfg = load_config()
    run_id = state.get("run_id", "")
    brief = state["brief"]
    depth = state.get("depth", "shallow")
    operator_id = state.get("operator_id", "local")

    if run_id:
        await append_progress(run_id, "coordinator", "Checking prior research...")

    prior = await find_prior_research(
        brief,
        operator_id=operator_id,
        threshold=cfg.prior_art_threshold,
    )
    if state.get("prior_research_id"):
        prior = [p for p in prior if p.id == state["prior_research_id"]] or prior[:1]

    delta_mode, delta_since = await should_use_delta_mode(prior, depth)
    graph_recall = await load_graph_recall(prior)

    return {
        **state,
        "prior_research": prior,
        "graph_recall": graph_recall,
        "delta_mode": delta_mode,
        "delta_since": delta_since.isoformat() if delta_since else None,
        "research_context": {
            "prior_count": len(prior),
            "delta_mode": delta_mode,
            "prior_summaries": [p.summary for p in prior[:3]],
        },
    }
