"""Discord Shim — HTTP glue between Discord gateway and Maya services (SEC-009).

Disabled by default. When enabled, requires either:
- ``DISCORD_PUBLIC_KEY`` (Ed25519 interaction signatures), or
- ``DISCORD_SHIM_SERVICE_TOKEN`` (Bearer token for internal glue).

Binds loopback by default.
"""

from __future__ import annotations

import hmac
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Discord Shim", version="0.1.0")

MAYA_GATEWAY_URL = os.getenv("MAYA_GATEWAY_URL", "http://localhost:8080").rstrip("/")


def shim_enabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return str(env.get("DISCORD_SHIM_ENABLED", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def service_token(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    return str(env.get("DISCORD_SHIM_SERVICE_TOKEN", "") or "").strip()


def discord_public_key(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    return str(env.get("DISCORD_PUBLIC_KEY", "") or "").strip()


def validate_shim_config(environ: dict[str, str] | None = None) -> None:
    if not shim_enabled(environ):
        raise RuntimeError(
            "Discord shim is disabled. Set DISCORD_SHIM_ENABLED=1 and configure "
            "DISCORD_PUBLIC_KEY or DISCORD_SHIM_SERVICE_TOKEN."
        )
    if not discord_public_key(environ) and not service_token(environ):
        raise RuntimeError(
            "Discord shim enabled but neither DISCORD_PUBLIC_KEY nor "
            "DISCORD_SHIM_SERVICE_TOKEN is set."
        )


def _verify_service_token(request: Request) -> bool:
    expected = service_token()
    if not expected:
        return False
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        got = auth[7:].strip()
        return hmac.compare_digest(got, expected)
    return False


def _verify_discord_ed25519(request: Request, body: bytes) -> bool:
    public_key_hex = discord_public_key()
    if not public_key_hex:
        return False
    signature = request.headers.get("x-signature-ed25519") or ""
    timestamp = request.headers.get("x-signature-timestamp") or ""
    if not signature or not timestamp:
        return False
    try:
        from nacl.exceptions import BadSignatureError
        from nacl.signing import VerifyKey
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PyNaCl required for Discord Ed25519 verification (pip install pynacl)",
        ) from exc
    try:
        key = VerifyKey(bytes.fromhex(public_key_hex))
        key.verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError):
        return False


async def authorize_interaction(request: Request, body: bytes) -> None:
    if not shim_enabled():
        raise HTTPException(status_code=503, detail="discord shim disabled")
    if _verify_service_token(request):
        return
    if _verify_discord_ed25519(request, body):
        return
    raise HTTPException(status_code=401, detail="unauthorized discord interaction")


async def _dispatch_cmd(name: str, options: list[dict], payload: dict) -> JSONResponse:
    args = {str(opt.get("name")): opt.get("value") for opt in options or [] if opt.get("name")}
    body = {
        "cmd_id": name,
        "args": args,
        "surface": "discord",
        "metadata": {
            "discord_user_id": str(
                payload.get("member", {}).get("user", {}).get("id")
                or payload.get("user", {}).get("id")
                or ""
            ),
            "discord_channel_id": str(payload.get("channel_id") or ""),
            "discord_guild_id": str(payload.get("guild_id") or ""),
            "discord_interaction_id": str(payload.get("id") or ""),
        },
    }
    headers = {}
    token = service_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{MAYA_GATEWAY_URL}/api/cmds/dispatch",
            json=body,
            headers=headers,
        )
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
    raw = await req.body()
    await authorize_interaction(req, raw)
    import json

    payload = json.loads(raw.decode("utf-8") or "{}")
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
            {
                "type": 4,
                "data": {"content": "Usage: /research query:<topic> [depth:shallow|deep]"},
            }
        )

    body = {
        "brief": query,
        "depth": depth,
        "discord_thread_id": payload.get("channel_id"),
    }
    headers = {}
    token = service_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{MAYA_GATEWAY_URL}/api/research/runs",
            json=body,
            headers=headers,
        )
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

    validate_shim_config()
    host = str(os.getenv("HOST", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
    uvicorn.run(
        "discord_shim.main:app",
        host=host,
        port=int(os.getenv("PORT", "8081")),
    )
