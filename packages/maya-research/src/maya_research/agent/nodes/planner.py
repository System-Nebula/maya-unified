"""Planner node — decompose brief into SubTasks."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from maya_contracts import ResearchDepth, ResearchPlan, ResearchSourceKind, SubTask, SubTaskType
from maya_research.agent.state import ResearchState
from maya_research.storage.run_repository import append_progress, save_plan
from maya_research.tasks.llm import LlmError, analyze_structured, llm_available


class _PlanOutput(BaseModel):
    rationale: str = ""
    subtasks: list[SubTask] = Field(default_factory=list)


async def planner_node(state: ResearchState) -> ResearchState:
    run_id = state.get("run_id", "")
    brief = state["brief"]
    depth = state.get("depth", "shallow")
    source_mask = set(state.get("source_mask") or ["web", "reddit", "local", "graph"])
    seed_urls = state.get("seed_urls") or []

    if run_id:
        await append_progress(run_id, "planner", "Generating research plan...")

    plan = await _build_plan(brief, depth, source_mask, seed_urls, state)
    auto_approve = depth == ResearchDepth.SHALLOW.value

    if run_id:
        await save_plan(run_id, plan, approved=auto_approve)
        await append_progress(
            run_id,
            "planner",
            f"Plan ready ({len(plan.subtasks)} sub-tasks)",
            details={"subtasks": [s.model_dump() for s in plan.subtasks]},
        )

    return {**state, "plan": plan, "plan_approved": auto_approve}


async def _build_plan(
    brief: str,
    depth: str,
    source_mask: set[str],
    seed_urls: list[str],
    state: ResearchState,
) -> ResearchPlan:
    if llm_available():
        try:
            prompt = _planner_prompt(brief, depth, source_mask, seed_urls, state)
            out = await analyze_structured(
                prompt,
                _PlanOutput,
                system="You are a research planner. Return JSON with rationale and subtasks.",
            )
            if out.subtasks:
                return ResearchPlan(subtasks=out.subtasks, rationale=out.rationale)
        except LlmError:
            pass
    return _heuristic_plan(brief, source_mask, seed_urls)


def _planner_prompt(
    brief: str,
    depth: str,
    source_mask: set[str],
    seed_urls: list[str],
    state: ResearchState,
) -> str:
    prior = state.get("prior_research") or []
    prior_text = "\n".join(f"- {p.title}: {p.summary[:200]}" for p in prior[:3])
    return (
        f"Brief: {brief}\nDepth: {depth}\nSources enabled: {', '.join(sorted(source_mask))}\n"
        f"Seed URLs: {seed_urls}\nPrior research:\n{prior_text or 'none'}\n"
        "Return subtasks with fields: id, type (web_search|page_fetch|reddit|firefox_history|graph_recall), "
        "query, source_hint, priority (1-3), depends_on."
    )


def _heuristic_plan(
    brief: str,
    source_mask: set[str],
    seed_urls: list[str],
) -> ResearchPlan:
    subtasks: list[SubTask] = []
    if ResearchSourceKind.WEB.value in source_mask:
        subtasks.append(
            SubTask(
                id=str(uuid.uuid4()),
                type=SubTaskType.WEB_SEARCH,
                query=brief,
                priority=1,
            )
        )
        subtasks.append(
            SubTask(
                id=str(uuid.uuid4()),
                type=SubTaskType.WEB_SEARCH,
                query=f"{brief} technical analysis",
                priority=2,
            )
        )
    for url in seed_urls:
        subtasks.append(
            SubTask(
                id=str(uuid.uuid4()),
                type=SubTaskType.PAGE_FETCH,
                query=url,
                source_hint=url,
                priority=1,
            )
        )
    if ResearchSourceKind.REDDIT.value in source_mask:
        for sub in ("StableDiffusion", "MachineLearning", "LocalLLaMA"):
            subtasks.append(
                SubTask(
                    id=str(uuid.uuid4()),
                    type=SubTaskType.REDDIT,
                    query=brief,
                    source_hint=f"r/{sub}",
                    priority=2,
                )
            )
    if ResearchSourceKind.LOCAL.value in source_mask:
        subtasks.append(
            SubTask(
                id=str(uuid.uuid4()),
                type=SubTaskType.FIREFOX_HISTORY,
                query=brief,
                priority=3,
            )
        )
    if ResearchSourceKind.GRAPH.value in source_mask:
        subtasks.append(
            SubTask(
                id=str(uuid.uuid4()),
                type=SubTaskType.GRAPH_RECALL,
                query=brief,
                priority=3,
            )
        )
    return ResearchPlan(
        subtasks=subtasks,
        rationale="Heuristic plan generated without LLM.",
    )
