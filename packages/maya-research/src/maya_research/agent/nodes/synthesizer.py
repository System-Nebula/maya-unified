"""Synthesizer node — dedup, merge, gap detection."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maya_contracts import ReportSection, ReportSectionKind, SynthesisBundle
from maya_research.agent.state import ResearchState
from maya_research.storage.run_repository import append_progress
from maya_research.tasks.llm import LlmError, analyze_structured, llm_available


class _SynthesisOutput(BaseModel):
    merged_claims: list[str] = Field(default_factory=list)
    uncovered_aspects: list[str] = Field(default_factory=list)
    technical_summary: str = ""
    sentiment_summary: str = ""


async def synthesizer_node(state: ResearchState) -> ResearchState:
    run_id = state.get("run_id", "")
    if run_id:
        await append_progress(run_id, "synthesizer", "Synthesizing findings...")

    source_dump = _build_source_dump(state)
    bundle = await _synthesize(source_dump, state)
    return {**state, "synthesis": bundle}


def _build_source_dump(state: ResearchState) -> str:
    parts: list[str] = []
    for p in state.get("fetched_pages") or []:
        parts.append(f"PAGE {p.url}\nTitle: {p.title}\n{p.markdown[:3000]}")
    for r in state.get("web_results") or []:
        parts.append(f"SEARCH {r.url}\n{r.title}\n{r.snippet}")
    for b in state.get("reddit_bundles") or []:
        parts.append(
            f"REDDIT r/{b.subreddit}\n{b.sentiment_summary}\nThemes: {b.recurring_themes}"
        )
    for item in state.get("graph_recall") or []:
        parts.append(f"PRIOR {item.get('title')}\n{item.get('summary')}")
    return "\n\n".join(parts[:40])


async def _synthesize(source_dump: str, state: ResearchState) -> SynthesisBundle:
    brief = state["brief"]
    if llm_available() and source_dump:
        try:
            prompt = (
                f"Research brief: {brief}\n\nSources:\n{source_dump[:12000]}\n\n"
                "Return JSON with merged_claims, uncovered_aspects, technical_summary, sentiment_summary."
            )
            out = await analyze_structured(prompt, _SynthesisOutput)
            sections = [
                ReportSection(
                    kind=ReportSectionKind.TECHNICAL,
                    title="Technical findings",
                    body=out.technical_summary or "\n".join(out.merged_claims[:10]),
                ),
                ReportSection(
                    kind=ReportSectionKind.SENTIMENT,
                    title="Community sentiment",
                    body=out.sentiment_summary or "No community signal collected.",
                ),
            ]
            if out.uncovered_aspects:
                sections.append(
                    ReportSection(
                        kind=ReportSectionKind.GAPS,
                        title="Gaps",
                        body="\n".join(f"- {g}" for g in out.uncovered_aspects),
                    )
                )
            return SynthesisBundle(
                merged_claims=out.merged_claims,
                uncovered_aspects=out.uncovered_aspects,
                source_weights={},
                sections=sections,
            )
        except LlmError:
            pass

    claims = []
    for p in state.get("fetched_pages") or []:
        claims.append(f"{p.title}: {p.markdown[:200]}...")
    for r in state.get("web_results") or []:
        claims.append(f"{r.title}: {r.snippet}")
    return SynthesisBundle(
        merged_claims=claims[:20],
        uncovered_aspects=_heuristic_gaps(brief, claims),
        source_weights={},
        sections=[
            ReportSection(
                kind=ReportSectionKind.SUMMARY,
                title="Summary",
                body="\n".join(claims[:8]) or "No sources collected.",
            )
        ],
    )


def _heuristic_gaps(brief: str, claims: list[str]) -> list[str]:
    if not claims:
        return [f"No sources found covering: {brief}"]
    return []
