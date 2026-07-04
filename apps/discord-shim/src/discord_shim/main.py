"""Discord Shim — HTTP glue between Discord gateway and Maya services."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Discord Shim", version="0.1.0")

MAYA_GATEWAY_URL = os.getenv("MAYA_GATEWAY_URL", "http://localhost:8080").rstrip("/")


async def _dispatch_cmd(name: str, options: list[dict], payload: dict) -> JSONResponse:
    args = {str(opt.get("name")): opt.get("value") for opt in options or [] if opt.get("name")}
    body = {
        "cmd_id": name,
        "args": args,
        "surface": "discord",
        "metadata": {
            "discord_user_id": str(payload.get("member", {}).get("user", {}).get("id") or payload.get("user", {}).get("id") or ""),
            "discord_channel_id": str(payload.get("channel_id") or ""),
            "discord_guild_id": str(payload.get("guild_id") or ""),
            "discord_interaction_id": str(payload.get("id") or ""),
        },
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{MAYA_GATEWAY_URL}/api/cmds/dispatch", json=body)
        if resp.status_code >= 400:
            return JSONResponse(
                {
                    "type": 4,
                    "data": {"content": f"Command failed: {resp.text[:500]}"},
                }
            )
        result = resp.json()
    if not result.get("ok"):
        return JSONResponse(
            {
                "type": 4,
                "data": {"content": result.get("error") or "Command failed."},
            }
        )
    text = str(result.get("text") or "Done.")
    return JSONResponse({"type": 4, "data": {"content": text[:1900]}})


@app.post("/discord/interaction")
async def interaction(req: Request):
    """Receive a Discord interaction and proxy it to the gateway."""
    payload = await req.json()
    interaction_type = payload.get("type", 0)

    if interaction_type == 1:
        return JSONResponse({"type": 1})

    data = payload.get("data", {})
    name = data.get("name", "")
    options = data.get("options") or []

    if name in {"help", "status", "imagine", "blend"}:
        return await _dispatch_cmd(name, options, payload)

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
