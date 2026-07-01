"""Reporter node — structured ResearchReport and markdown artifact."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from maya_contracts import (
    CitedSource,
    ReportMetadata,
    ReportSection,
    ReportSectionKind,
    ResearchDepth,
    ResearchReport,
)
from maya_research.agent.state import ResearchState
from maya_research.storage.artifacts import artifact_public_url, store_markdown
from maya_research.storage.run_repository import append_progress


async def reporter_node(state: ResearchState) -> ResearchState:
    run_id = state.get("run_id", "")
    started = time.monotonic()
    synthesis = state.get("synthesis")
    brief = state["brief"]
    depth = state.get("depth", "shallow")

    sections: list[ReportSection] = list(synthesis.sections) if synthesis else []
    if not sections:
        sections = [
            ReportSection(
                kind=ReportSectionKind.SUMMARY,
                title="Summary",
                body="Research completed with limited source material.",
            )
        ]

    sources = _collect_sources(state)
    exec_summary = _executive_summary(synthesis, sources)
    uncovered = list(synthesis.uncovered_aspects) if synthesis else []
    followups = _suggest_followups(brief, uncovered)

    report = ResearchReport(
        title=f"{brief[:80]} — Research Report",
        brief=brief,
        executive_summary=exec_summary,
        sections=sections,
        sources=sources,
        uncovered_aspects=uncovered,
        suggested_followups=followups,
        metadata=ReportMetadata(
            depth=ResearchDepth(depth),
            duration_seconds=time.monotonic() - started,
            source_counts={
                "web": len(state.get("web_results") or []),
                "pages": len(state.get("fetched_pages") or []),
                "reddit": len(state.get("reddit_bundles") or []),
                "operator": len(getattr(state.get("operator_context"), "items", []) or []),
            },
            model_used="heuristic",
            delta_mode=bool(state.get("delta_mode")),
        ),
    )

    md = _render_markdown(report)
    artifact_id, artifact_key = await store_markdown(md, suffix="md")

    if run_id:
        await append_progress(
            run_id,
            "reporter",
            "Report ready",
            details={"artifact_url": artifact_public_url(artifact_id)},
        )

    return {
        **state,
        "report": report,
        "artifact_id": artifact_id,
        "artifact_key": artifact_key,
    }


def _collect_sources(state: ResearchState) -> list[CitedSource]:
    sources: list[CitedSource] = []
    seen: set[str] = set()
    for p in state.get("fetched_pages") or []:
        if p.url in seen:
            continue
        seen.add(p.url)
        sources.append(
            CitedSource(
                url=p.url,
                title=p.title,
                credibility_score=p.credibility_score,
                snippet=p.markdown[:240],
            )
        )
    for r in state.get("web_results") or []:
        if r.url in seen:
            continue
        seen.add(r.url)
        sources.append(
            CitedSource(
                url=r.url,
                title=r.title,
                credibility_score=r.credibility_score,
                snippet=r.snippet[:240],
            )
        )
    return sources[:30]


def _executive_summary(synthesis, sources: list[CitedSource]) -> str:
    if synthesis and synthesis.merged_claims:
        return synthesis.merged_claims[0][:500]
    if sources:
        return f"Synthesized {len(sources)} sources."
    return "Research completed with limited findings."


def _suggest_followups(brief: str, gaps: list[str]) -> list[str]:
    followups = [f'/research "{brief} follow-up" --depth deep']
    for gap in gaps[:3]:
        followups.append(f'/research "{gap}" --depth deep')
    return followups


def _render_markdown(report: ResearchReport) -> str:
    lines = [
        f"# {report.title}",
        "",
        f"*Generated {datetime.now(timezone.utc).isoformat()}*",
        "",
        "## Executive Summary",
        report.executive_summary,
        "",
    ]
    for section in report.sections:
        lines.extend([f"## {section.title}", section.body, ""])
    if report.sources:
        lines.append("## Sources")
        for s in report.sources:
            lines.append(f"- [{s.title}]({s.url}) (credibility: {s.credibility_score:.2f})")
    if report.uncovered_aspects:
        lines.append("## Uncovered Aspects")
        for g in report.uncovered_aspects:
            lines.append(f"- {g}")
    if report.suggested_followups:
        lines.append("## Suggested Follow-ups")
        for f in report.suggested_followups:
            lines.append(f"- {f}")
    return "\n".join(lines)
