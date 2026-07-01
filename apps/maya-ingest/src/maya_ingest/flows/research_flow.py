"""Prefect flow wrapper for research runs."""

from __future__ import annotations

from prefect import flow, get_run_logger

from maya_research.runner import execute_run


@flow(name="maya-research", retries=1)
async def research_flow(run_id: str, *, execution_only: bool = False) -> dict:
    logger = get_run_logger()
    logger.info("research flow %s execution_only=%s", run_id, execution_only)
    final = await execute_run(run_id, execution_only=execution_only)
    report = final.get("report")
    return {
        "run_id": run_id,
        "artifact_id": final.get("artifact_id"),
        "report_title": report.title if report else None,
        "errors": final.get("errors") or [],
    }
