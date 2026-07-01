"""Graph memory recall node — inject prior research context."""

from __future__ import annotations

from maya_contracts import SubTaskType
from maya_research.agent.state import ResearchState
from maya_research.storage.run_repository import append_progress


async def graph_memory_node(state: ResearchState) -> ResearchState:
    plan = state.get("plan")
    if plan and not any(s.type == SubTaskType.GRAPH_RECALL for s in plan.subtasks):
        return state

    recall = state.get("graph_recall") or []
    if state.get("run_id"):
        await append_progress(
            state["run_id"],
            "graph_recall",
            f"Loaded {len(recall)} prior research nodes",
        )
    return {**state, "graph_recall": recall}
