"""LangGraph research agent definition."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from maya_research.agent.nodes.coordinator import coordinator_node
from maya_research.agent.nodes.firefox_reader import firefox_reader_node
from maya_research.agent.nodes.graph_memory import graph_memory_node
from maya_research.agent.nodes.page_fetcher import page_fetcher_node
from maya_research.agent.nodes.persister import persister_node
from maya_research.agent.nodes.planner import planner_node
from maya_research.agent.nodes.reddit_agent import reddit_agent_node
from maya_research.agent.nodes.reporter import reporter_node
from maya_research.agent.nodes.synthesizer import synthesizer_node
from maya_research.agent.nodes.web_researcher import web_researcher_node
from maya_research.agent.state import ResearchState


def _approval_gate(state: ResearchState) -> str:
    if state.get("plan_approved"):
        return "execute"
    return "wait"


def build_research_graph():
    graph = StateGraph(ResearchState)

    graph.add_node("coordinator", coordinator_node)
    graph.add_node("planner", planner_node)
    graph.add_node("graph_memory", graph_memory_node)
    graph.add_node("firefox_reader", firefox_reader_node)
    graph.add_node("web_researcher", web_researcher_node)
    graph.add_node("reddit_agent", reddit_agent_node)
    graph.add_node("page_fetcher", page_fetcher_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("reporter", reporter_node)
    graph.add_node("persister", persister_node)

    graph.set_entry_point("coordinator")
    graph.add_edge("coordinator", "planner")
    graph.add_conditional_edges(
        "planner",
        _approval_gate,
        {"execute": "graph_memory", "wait": END},
    )
    graph.add_edge("graph_memory", "firefox_reader")
    graph.add_edge("firefox_reader", "web_researcher")
    graph.add_edge("web_researcher", "reddit_agent")
    graph.add_edge("reddit_agent", "page_fetcher")
    graph.add_edge("page_fetcher", "synthesizer")
    graph.add_edge("synthesizer", "reporter")
    graph.add_edge("reporter", "persister")
    graph.add_edge("persister", END)

    return graph.compile()


async def run_research(state: ResearchState) -> ResearchState:
    graph = build_research_graph()
    final: ResearchState = state
    async for event in graph.astream(state, stream_mode="values"):
        final = event
    return final


_EXECUTION_NODES = (
    graph_memory_node,
    firefox_reader_node,
    web_researcher_node,
    reddit_agent_node,
    page_fetcher_node,
    synthesizer_node,
    reporter_node,
    persister_node,
)


async def run_research_execution(state: ResearchState) -> ResearchState:
    """Run execution phase after plan approval (deep mode)."""
    current = {**state, "plan_approved": True}
    for node in _EXECUTION_NODES:
        current = await node(current)
    return current


async def run_research_planning(state: ResearchState) -> ResearchState:
    """Coordinator + planner only."""
    current = await coordinator_node(state)
    current = await planner_node(current)
    return current
