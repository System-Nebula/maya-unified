"""Tests for imagine debug API."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from maya_image.api import job_status
from maya_image.types.image_job import ImageJob, ImageJobInput, ImageJobStatus


@pytest.mark.asyncio
async def test_job_status_includes_correlation_metadata() -> None:
    job = ImageJob(
        id="job-abc",
        provider_key="comfyui:graph",
        provider_job_id="comfy-prompt-1",
        status=ImageJobStatus.COMPLETED,
        input=ImageJobInput(
            prompt="a fox",
            metadata={
                "corr_id": "c_test123",
                "trace_id": "trace999",
                "workflow_id": "wf-zit",
                "model_key": "z-image-turbo",
                "surface": "dashboard",
            },
        ),
        created_at=datetime(2026, 7, 4, 18, 0, 0, tzinfo=timezone.utc),
    )
    mock_service = MagicMock()
    mock_service.get_job.return_value = job
    mock_service.get_memory_job.return_value = None

    with patch("maya_image.api.get_image_service", return_value=mock_service):
        body = await job_status("job-abc")

    assert body["id"] == "job-abc"
    assert body["provider_job_id"] == "comfy-prompt-1"
    assert body["metadata"]["corr_id"] == "c_test123"
    assert body["metadata"]["trace_id"] == "trace999"
    assert body["metadata"]["workflow_id"] == "wf-zit"
