"""Discord Shim — HTTP glue between Discord gateway and Maya services."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Discord Shim", version="0.1.0")

MAYA_GATEWAY_URL = os.getenv("MAYA_GATEWAY_URL", "http://localhost:8080").rstrip("/")


@app.post("/discord/interaction")
async def interaction(req: Request):
    """Receive a Discord interaction and proxy it to the gateway."""
    payload = await req.json()
    interaction_type = payload.get("type", 0)

    if interaction_type == 1:
        return JSONResponse({"type": 1})

    data = payload.get("data", {})
    name = data.get("name", "")
    if name == "research":
        return await _handle_research_slash(payload)

    return JSONResponse(
        {
            "type": 4,
            "data": {
                "content": (
                    f"Shim received `/{name}`. "
                    "Wire additional commands to MAYA_GATEWAY_URL in downstream bot."
                )
            },
        }
    )


async def _handle_research_slash(payload: dict) -> JSONResponse:
    options = payload.get("data", {}).get("options") or []
    query = ""
    depth = "shallow"
    for opt in options:
        if opt.get("name") == "query":
            query = opt.get("value") or ""
        if opt.get("name") == "depth":
            depth = opt.get("value") or "shallow"

    if not query:
        return JSONResponse(
            {"type": 4, "data": {"content": "Usage: /research query:<topic> [depth:shallow|deep]"}}
        )

    body = {
        "brief": query,
        "depth": depth,
        "discord_thread_id": payload.get("channel_id"),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{MAYA_GATEWAY_URL}/api/research/runs", json=body)
        if resp.status_code >= 400:
            return JSONResponse(
                {
                    "type": 4,
                    "data": {"content": f"Research start failed: {resp.text[:500]}"},
                }
            )
        run = resp.json()

    return JSONResponse(
        {
            "type": 4,
            "data": {
                "content": (
                    f"Research started: **{query}**\n"
                    f"Run ID: `{run.get('id')}`\n"
                    f"Status: {run.get('status')}\n"
                    "Progress updates stream via downstream thread webhook."
                )
            },
        }
    )


def run() -> None:
    import uvicorn

    uvicorn.run(
        "discord_shim.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8081")),
    )
