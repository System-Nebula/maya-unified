"""Frontend player telemetry beacons (OTEL ui.player.* spans)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.tracing import corr_span

router = APIRouter(tags=["telemetry"])


class TelemetryEventBody(BaseModel):
    event: str
    corr_id: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/telemetry/event")
async def post_telemetry_event(body: TelemetryEventBody) -> dict[str, bool]:
    span_attrs: dict[str, Any] = {"event": body.event, **body.attrs}
    if body.corr_id:
        span_attrs["corr_id"] = body.corr_id
        span_attrs["chat.corr_id"] = body.corr_id
    with corr_span(f"ui.player.{body.event}", **span_attrs):
        pass
    return {"ok": True}
