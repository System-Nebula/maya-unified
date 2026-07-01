"""Analyze a GitHub release diff and persist structured summary."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from maya_contracts import (
    AnalysisKind,
    AnalysisStatus,
    AnalysisSummary,
    FileChange,
    NotificationKind,
    ReleaseAnalysis,
)
from maya_db import (
    Channel as ChannelDB,
    FeedAnalysis as FeedAnalysisDB,
    Notification as NotificationDB,
    Video as VideoDB,
    get_async_session,
)
from maya_feeds.github_api import (
    GitHubApiClient,
    chunk_patches,
    parse_repo_slug,
    relevant_files,
)
from maya_ingest.tasks.llm import LlmError, analyze_structured, llm_available
from prefect import flow, get_run_logger, task
from sqlalchemy import select


def _default_ignore() -> list[str]:
    return [
        r"^tests?/",
        r"\.lock$",
        r"^\.github/",
        r"^Cargo\.lock$",
        r"CHANGELOG",
    ]


def _build_chunk_prompt(
    repo: str, from_tag: str | None, to_tag: str, files: list, release_notes: str | None
) -> str:
    parts = [
        f"Analyze this GitHub release diff for {repo} ({from_tag or 'start'} → {to_tag}).",
        "Return JSON matching: summary (string), breaking_changes (string[]), "
        "affected_subsystems (string[]), doc_sections (string[]).",
    ]
    if release_notes:
        parts.append(f"Release notes:\n{release_notes[:4000]}")
    for f in files:
        parts.append(f"\n--- {f.filename} ({f.status} +{f.additions}/-{f.deletions}) ---")
        if f.patch:
            parts.append(f.patch)
    return "\n".join(parts)


@task
async def _run_release_analysis(video_uuid: str) -> bool:
    logger = get_run_logger()
    vid = UUID(video_uuid)
    async for session in get_async_session():
        video = await session.get(VideoDB, vid)
        if video is None:
            logger.warning("video %s not found", video_uuid)
            return False
        channel = await session.get(ChannelDB, video.channel_id)
        if channel is None:
            return False

        video.analysis_status = AnalysisStatus.RUNNING.value
        await session.flush()

        owner, repo = parse_repo_slug(channel.handle)
        to_tag = video.video_id
        release_url = f"https://github.com/{owner}/{repo}/releases/tag/{to_tag}"
        ignore = _default_ignore()

        try:
            async with GitHubApiClient() as gh:
                prev_tag = await gh.resolve_prev_tag(owner, repo, to_tag)
                if prev_tag:
                    compare = await gh.compare_tags(owner, repo, prev_tag, to_tag)
                    filtered = relevant_files(compare.files, ignore)
                else:
                    prev_tag = None
                    filtered = []

            file_changes = [
                FileChange(
                    filename=f.filename,
                    status=f.status,
                    additions=f.additions,
                    deletions=f.deletions,
                    patch=f.patch,
                )
                for f in filtered
            ]

            analysis: AnalysisSummary | None = None
            if llm_available() and filtered:
                merged = AnalysisSummary(
                    summary="",
                    breaking_changes=[],
                    affected_subsystems=[],
                    doc_sections=[],
                )
                for chunk in chunk_patches(filtered):
                    prompt = _build_chunk_prompt(
                        f"{owner}/{repo}", prev_tag, to_tag, chunk, video.description
                    )
                    try:
                        partial = await analyze_structured(
                            prompt,
                            AnalysisSummary,
                            system=(
                                "You are a release analyst. Summarize code changes concisely. "
                                "Respond with valid JSON only."
                            ),
                        )
                        if not merged.summary:
                            merged = partial
                        else:
                            merged = AnalysisSummary(
                                summary=merged.summary + "\n" + partial.summary,
                                breaking_changes=list(
                                    set(merged.breaking_changes + partial.breaking_changes)
                                ),
                                affected_subsystems=list(
                                    set(
                                        merged.affected_subsystems
                                        + partial.affected_subsystems
                                    )
                                ),
                                doc_sections=list(
                                    set(merged.doc_sections + partial.doc_sections)
                                ),
                            )
                    except LlmError as exc:
                        logger.warning("LLM chunk failed: %s", exc)
                analysis = merged
            elif filtered:
                analysis = AnalysisSummary(
                    summary=(
                        f"Release {to_tag}: {len(filtered)} relevant files changed "
                        f"({sum(f.additions for f in filtered)} additions, "
                        f"{sum(f.deletions for f in filtered)} deletions). "
                        "LLM analysis skipped (no API key)."
                    ),
                    affected_subsystems=sorted({f.filename.split("/")[0] for f in filtered}),
                )

            now = datetime.now(timezone.utc)
            payload = ReleaseAnalysis(
                repo=f"{owner}/{repo}",
                from_tag=prev_tag,
                to_tag=to_tag,
                release_url=release_url,
                release_notes=video.description,
                file_changes=file_changes,
                analysis=analysis,
                generated_at=now,
            )

            existing = (
                await session.execute(
                    select(FeedAnalysisDB).where(FeedAnalysisDB.entry_id == video.id)
                )
            ).scalar_one_or_none()
            if existing:
                existing.from_tag = prev_tag
                existing.to_tag = to_tag
                existing.release_url = release_url
                existing.payload = payload.model_dump(mode="json")
                existing.generated_at = now
                existing.status = AnalysisStatus.DONE.value
            else:
                session.add(
                    FeedAnalysisDB(
                        channel_id=channel.id,
                        entry_id=video.id,
                        kind=AnalysisKind.RELEASE_DIFF.value,
                        from_tag=prev_tag,
                        to_tag=to_tag,
                        release_url=release_url,
                        status=AnalysisStatus.DONE.value,
                        payload=payload.model_dump(mode="json"),
                        generated_at=now,
                    )
                )

            video.analysis_status = AnalysisStatus.DONE.value
            session.add(
                NotificationDB(
                    kind=NotificationKind.RELEASE_ANALYZED.value,
                    channel_id=channel.id,
                    video_id=video.id,
                    title=f"Release analyzed: {to_tag}",
                    body=f"{owner}/{repo}",
                    link=f"/api/intel/releases?repo={owner}/{repo}",
                    read=False,
                )
            )
            await session.commit()
            return True
        except Exception as exc:
            logger.exception("release analysis failed for %s: %s", video_uuid, exc)
            video.analysis_status = AnalysisStatus.FAILED.value
            await session.commit()
            return False
    return False


@flow(name="analyze-release")
async def analyze_release(video_uuid: str) -> bool:
    """Fetch GitHub compare diff and run LLM analysis for one release entry."""
    return await _run_release_analysis(video_uuid)
