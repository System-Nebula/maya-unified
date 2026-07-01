"""Health, status, and observability endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/status", tags=["status"])


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str


class SystemStatus(BaseModel):
    gateway: str
    database: str
    uptime_seconds: float


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/ready", response_model=SystemStatus)
async def ready():
    return SystemStatus(
        gateway="ok",
        database="unknown",  # wired up when db package has health check
        uptime_seconds=0.0,
    )
