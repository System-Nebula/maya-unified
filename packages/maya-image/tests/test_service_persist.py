"""Tests for image_jobs DB record shaping."""

from __future__ import annotations

from datetime import datetime, timezone

from maya_image.service import ImageJobService
from maya_image.types.image_job import ImageJob, ImageJobInput, ImageJobStatus


def test_build_job_record_sets_created_at_from_started_at() -> None:
    started = datetime(2026, 7, 4, 18, 0, 0, tzinfo=timezone.utc)
    job = ImageJob(
        provider_key="comfyui:graph",
        status=ImageJobStatus.SUBMITTED,
        input=ImageJobInput(prompt="a fox"),
        started_at=started,
    )
    svc = object.__new__(ImageJobService)
    row = svc._build_job_record(job)
    assert row.created_at == started


def test_build_job_record_sets_created_at_when_missing() -> None:
    job = ImageJob(
        provider_key="comfyui:graph",
        status=ImageJobStatus.SUBMITTED,
        input=ImageJobInput(prompt="a fox"),
        started_at=None,
    )
    svc = object.__new__(ImageJobService)
    row = svc._build_job_record(job)
    assert row.created_at is not None
