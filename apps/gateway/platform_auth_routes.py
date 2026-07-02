"""Platform OAuth stubs — UI shell until maya-gateway platform auth is wired."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["platform-auth"])

_SUPPORTED_PROVIDERS = ("google", "discord", "github")


@router.get("/api/platform/auth/status")
async def platform_auth_status():
    return {
        "oauth_available": False,
        "providers": [],
        "message": "Platform OAuth not configured in this deployment.",
    }


@router.get("/api/platform/auth/login/{provider}")
async def platform_oauth_login(provider: str):
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")
    raise HTTPException(
        status_code=501,
        detail="Platform OAuth is not configured yet. Use operator username/password login.",
    )
