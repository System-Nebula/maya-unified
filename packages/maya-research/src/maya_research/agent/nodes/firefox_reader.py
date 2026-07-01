"""Firefox / operator history reader node."""

from __future__ import annotations

from maya_contracts import OperatorContext, SubTaskType
from maya_research.adapters.operator_history import NullOperatorHistoryReader, OperatorHistoryReader
from maya_research.agent.state import ResearchState
from maya_research.storage.run_repository import append_progress

_default_reader: OperatorHistoryReader = NullOperatorHistoryReader()


def set_operator_history_reader(reader: OperatorHistoryReader) -> None:
    global _default_reader
    _default_reader = reader


async def firefox_reader_node(state: ResearchState) -> ResearchState:
    plan = state.get("plan")
    if not plan or not any(s.type == SubTaskType.FIREFOX_HISTORY for s in plan.subtasks):
        return {**state, "operator_context": OperatorContext(query=state["brief"], items=[])}

    query = state["brief"]
    for task in plan.subtasks:
        if task.type == SubTaskType.FIREFOX_HISTORY:
            query = task.query
            break

    try:
        ctx = await _default_reader.for_research(query)
        if state.get("run_id"):
            await append_progress(
                state["run_id"],
                "firefox_history",
                f"Operator history: {len(ctx.items)} sources",
            )
        return {**state, "operator_context": ctx}
    except Exception as exc:
        errors = list(state.get("errors") or [])
        errors.append(f"firefox_history failed: {exc}")
        return {
            **state,
            "operator_context": OperatorContext(query=query, items=[]),
            "errors": errors,
        }
