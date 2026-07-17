"""Legacy /duplex path — redirects to main conversation UI."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["duplex"])


@router.get("/duplex")
@router.get("/duplex/")
async def duplex_redirect():
    return RedirectResponse(url="/dashboard/conversation.html", status_code=302)


@router.get("/duplex/{path:path}")
async def duplex_legacy_redirect(path: str):
    if path.startswith("static/"):
        return RedirectResponse(url="/dashboard/conversation.html", status_code=302)
    return RedirectResponse(url="/dashboard/conversation.html", status_code=302)
