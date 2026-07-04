"""Arena runnable pool filtering and partial submit failure handling."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

# The arena DB layer was never ported into maya-unified (broken since the
# initial platform merge); skip until the arena feature lands here.
pytest.importorskip("maya_image.db", reason="maya_image.db not ported to maya-unified")

from maya_image.service import ImageJobService
from maya_image.workflows import get_workflow
from maya_image.types.image_job import ImageJobInput, ImageJobStatus, ImageMode


class _ComfyProvider:
    def __init__(self, *, fail_slot: str | None = None):
        self.fail_slot = fail_slot

    async def submit(self, request):
        if self.fail_slot and request.metadata.get("arena_slot") == self.fail_slot:
            raise RuntimeError("workflow endpoint 404")
        return "comfy-job-1", ImageJobStatus.SUBMITTED

    async def poll(self, provider_job_id):
        from maya_image.types.image_job import ImageJobOutput, ImageOutput

        return (
            ImageJobStatus.COMPLETED,
            ImageJobOutput(
                provider="comfyui",
                model="krea2-turbo",
                outputs=[ImageOutput(url="https://example.com/out.png", mime_type="image/png")],
                raw_response={},
            ),
            None,
        )

    async def upload_file(self, path: str):
        return f"https://cdn.example/{path.split('/')[-1]}"


class _Storage:
    async def mirror_url(self, url: str, *, filename=None, subdir="outputs", mime_type=None):
        from maya_image.types.image_job import ImageOutput

        return ImageOutput(url=url, local_path=f"/tmp/{subdir}/out.png", mime_type=mime_type or "image/png")


def _make_service(*, fail_slot: str | None = None) -> ImageJobService:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from maya_image.arena.service import ArenaService
    from maya_image.db.arena import Base as ArenaBase
    from maya_image.db.image_job import Base as ImageBase

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ArenaBase.metadata.create_all(engine)
    ImageBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    class _DB:
        def get_session(self):
            return session_factory()

    db = _DB()
    arena_svc = ArenaService()
    arena_svc._db = db

    ok_provider = _ComfyProvider()
    fail_provider = _ComfyProvider(fail_slot=fail_slot)

    def provider_router(_key):
        if fail_slot:
            return fail_provider
        return ok_provider

    svc = ImageJobService()
    svc._db = db
    svc._arena = arena_svc
    svc._storage = _Storage()
    svc._provider = provider_router
    return svc


def test_submit_workflow_arena_opponent_failure_returns_failed_job_b():
    svc = _make_service(fail_slot="b")
    krea = get_workflow("krea2-turbo-t2i")
    request = ImageJobInput(
        prompt="a cat",
        mode=ImageMode.ARENA,
        metadata={"workflow_id": krea.id},
    )

    with patch("maya_image.service.random.choice") as mock_choice:
        mock_choice.return_value = get_workflow("z-image-turbo-t2i")
        result = asyncio.run(svc.submit_workflow_arena(request, source_workflow_id=krea.id))

    assert "battle_id" in result
    job_a = svc._memory_jobs[result["job_ids"]["a"]]
    job_b = svc._memory_jobs[result["job_ids"]["b"]]
    assert job_a.status != ImageJobStatus.FAILED
    assert job_b.status == ImageJobStatus.FAILED
    assert "404" in (job_b.error or "")


def test_submit_arena_raises_when_pool_too_small():
    svc = _make_service()
    request = ImageJobInput(prompt="a cat", mode=ImageMode.ARENA)

    with patch("maya_image.service.list_arena_runnable_workflows", return_value=[get_workflow("krea2-turbo-t2i")]):
        with pytest.raises(RuntimeError, match="no arena-ready local workflows"):
            asyncio.run(svc.submit_arena(request))


def test_submit_workflow_arena_survives_arena_db_timeout():
    """Arena metadata DB failure must not abort after jobs are submitted."""
    svc = _make_service()
    real_db_op = svc._db_op

    async def selective_db_op(label, func, *args, **kwargs):
        if label.startswith("arena."):
            return None
        return await real_db_op(label, func, *args, **kwargs)

    svc._db_op = selective_db_op

    krea = get_workflow("krea2-turbo-t2i")
    request = ImageJobInput(
        prompt="a cat",
        mode=ImageMode.ARENA,
        metadata={"workflow_id": krea.id},
    )

    with patch("maya_image.service.random.choice") as mock_choice:
        mock_choice.return_value = get_workflow("z-image-turbo-t2i")
        result = asyncio.run(svc.submit_workflow_arena(request, source_workflow_id=krea.id))

    assert result["battle_id"]
    assert result["job_ids"]["a"] in svc._memory_jobs
    assert result["job_ids"]["b"] in svc._memory_jobs
    assert result["candidate_ids"]["a"]
    assert result["candidate_ids"]["b"]
    finalized = asyncio.run(
        svc.finalize_arena_jobs(
            result["battle_id"],
            result["job_ids"],
            result["candidate_ids"],
            max_polls=1,
            poll_interval=0,
        )
    )
    assert finalized["a"].output is not None
    assert finalized["b"].output is not None


def test_submit_workflow_arena_submits_slots_sequentially_by_default():
    import time

    svc = _make_service()
    start_times: list[float] = []

    class _TimedProvider(_ComfyProvider):
        async def submit(self, request):
            start_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            return "comfy-job-1", ImageJobStatus.SUBMITTED

    svc._provider = lambda _key: _TimedProvider()

    krea = get_workflow("krea2-turbo-t2i")
    request = ImageJobInput(
        prompt="a cat",
        mode=ImageMode.ARENA,
        metadata={"workflow_id": krea.id, "discord_interaction_id": "sequential-test"},
    )
    with patch("maya_image.service.random.choice") as mock_choice:
        mock_choice.return_value = get_workflow("z-image-turbo-t2i")
        asyncio.run(svc.submit_workflow_arena(request, source_workflow_id=krea.id))

    assert len(start_times) == 2
    assert start_times[1] - start_times[0] >= 0.04


def test_select_arena_contenders_prefers_light_and_heavy_pair():
    svc = _make_service()
    for _ in range(30):
        a, b = svc._select_arena_contenders()
        names = {a.get("workflow_name"), b.get("workflow_name")}
        assert not (names <= svc._ARENA_HEAVY_WORKFLOW_NAMES), (
            f"paired two heavy workflows: {names}"
        )
        if names & svc._ARENA_LIGHT_WORKFLOW_NAMES and names & svc._ARENA_HEAVY_WORKFLOW_NAMES:
            return
    pytest.fail("never selected a light+heavy pair in 30 draws")


def test_salvage_inflight_arena_returns_completed_slot():
    svc = _make_service()
    from maya_image.types.image_job import ImageJob, ImageJobOutput, ImageOutput

    request = ImageJobInput(
        prompt="a cat",
        mode=ImageMode.ARENA,
        metadata={"discord_interaction_id": "salvage-test", "arena_slot": "a"},
    )
    completed = ImageJob(
        provider_key="comfyui:graph",
        status=ImageJobStatus.COMPLETED,
        input=request,
        output=ImageJobOutput(
            provider="comfyui",
            model="krea2-turbo",
            outputs=[ImageOutput(url="https://example.com/out.png")],
        ),
    )
    svc._memory_jobs[completed.id] = completed

    salvaged = asyncio.run(
        svc.salvage_inflight_arena(
            ImageJobInput(
                prompt="a cat",
                mode=ImageMode.ARENA,
                metadata={"discord_interaction_id": "salvage-test"},
            )
        )
    )
    assert salvaged is not None
    assert salvaged["a"].output is not None


def test_resolve_request_arena_uses_shared_size_not_workflow_aspect():
    from maya_image.comfy_bind import build_values_from_request

    service = ImageJobService()
    z_wf = get_workflow("z-image-turbo-t2i")
    krea_wf = get_workflow("krea2-turbo-t2i")
    assert z_wf.params.get("aspect") == "9:16"
    assert krea_wf.params.get("aspect") == "1:1"

    base = ImageJobInput(prompt="test", mode=ImageMode.ARENA, size="1024x1024")
    req_a = base.model_copy(
        update={"metadata": {"workflow_id": z_wf.id, "arena_slot": "a"}},
    )
    req_b = base.model_copy(
        update={"metadata": {"workflow_id": krea_wf.id, "arena_slot": "b"}},
    )

    _, resolved_a = service._resolve_request("comfyui:graph", req_a)
    _, resolved_b = service._resolve_request("comfyui:graph", req_b)

    assert resolved_a.size == "1024x1024"
    assert resolved_b.size == "1024x1024"
    assert "aspect" not in resolved_a.metadata
    assert "aspect" not in resolved_b.metadata

    values_a = build_values_from_request(resolved_a, params=z_wf.params)
    values_b = build_values_from_request(resolved_b, params=krea_wf.params)
    assert (values_a["width"], values_a["height"]) == (1024, 1024)
    assert (values_b["width"], values_b["height"]) == (1024, 1024)
