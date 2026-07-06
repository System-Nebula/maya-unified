"""Music streaming proxy for the dashboard mini-player.

Resolves a track (URL or search text) with yt-dlp and transcodes to MP3 on the fly
so the browser plays it same-origin — no CORS, no signed-URL expiry, and YouTube
works too (the server does the fetch). Mirrors the Discord ``_make_ytdlp_piped_audio``
pipeline, reusing its extractor/cookie CLI helpers.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import sys

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from maya_db.models.operator import OperatorUser

from services.auth.deps import require_operator

router = APIRouter(prefix="/api/media", tags=["media"])
log = logging.getLogger("maya-unified.media")

_URL_RE = re.compile(r"^https?://", re.I)
_CHUNK = 64 * 1024


def _resolve_target(q: str) -> str:
    """A bare (non-URL) query becomes a top YouTube search result."""
    q = q.strip()
    if _URL_RE.match(q):
        return q
    return f"ytsearch1:{q}"


@router.get("/stream")
async def stream_track(
    _op: Annotated[OperatorUser, Depends(require_operator)],
    q: str = Query(..., min_length=1),
):
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=503, detail="ffmpeg not available on the server")

    from services.discord.youtube_patch import _cookie_cli_args, _extractor_args_cli

    target = _resolve_target(q)
    ytdl_cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        "bestaudio/best",
        "--no-playlist",
        "--no-warnings",
        "-q",
        *_extractor_args_cli(),
        *_cookie_cli_args(),
        "-o",
        "-",
        "--",
        target,
    ]
    ff_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-vn",
        "-f",
        "mp3",
        "-b:a",
        "192k",
        "pipe:1",
    ]

    ytdl = subprocess.Popen(
        ytdl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
    )
    ff = subprocess.Popen(
        ff_cmd, stdin=ytdl.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    # Let yt-dlp receive SIGPIPE if ffmpeg exits early.
    if ytdl.stdout is not None:
        ytdl.stdout.close()

    def _cleanup() -> None:
        for proc in (ff, ytdl):
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception:  # noqa: BLE001
                pass

    async def _gen():
        try:
            while True:
                chunk = await asyncio.to_thread(ff.stdout.read, _CHUNK)
                if not chunk:
                    break
                yield chunk
        except asyncio.CancelledError:
            raise
        finally:
            _cleanup()

    headers = {"Cache-Control": "no-store", "Accept-Ranges": "none"}
    return StreamingResponse(_gen(), media_type="audio/mpeg", headers=headers)


# Lightweight per-query metadata (title/artist/cover/duration) for the mini-player's
# now-playing panel. yt-dlp is slow to spawn, so results are memoised in-process and the
# frontend only asks for the currently playing track.
_META_CACHE: dict[str, dict[str, object]] = {}
_META_CACHE_MAX = 512
_EMPTY_META: dict[str, object] = {"title": "", "artist": "", "thumbnail": "", "duration": None}


def _extract_meta(target: str) -> dict[str, object]:
    """Resolve a single track's metadata with yt-dlp (no download)."""
    import yt_dlp

    from services.discord.youtube_patch import _cookie_opts

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        **_cookie_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)
    # A ``ytsearch1:`` target comes back as a one-entry playlist.
    if info and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else info
    info = info or {}
    thumb = str(info.get("thumbnail") or "").strip()
    if not thumb:
        thumbs = info.get("thumbnails") or []
        if thumbs:
            thumb = str((thumbs[-1] or {}).get("url") or "").strip()
    duration = info.get("duration")
    return {
        "title": str(info.get("track") or info.get("title") or "").strip(),
        "artist": str(
            info.get("artist") or info.get("uploader") or info.get("channel") or ""
        ).strip(),
        "thumbnail": thumb,
        "duration": float(duration) if isinstance(duration, (int, float)) else None,
    }


@router.get("/meta")
async def track_meta(
    _op: Annotated[OperatorUser, Depends(require_operator)],
    q: str = Query(..., min_length=1),
):
    key = q.strip()
    cached = _META_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        meta = await asyncio.to_thread(_extract_meta, _resolve_target(key))
    except Exception:  # noqa: BLE001 - metadata is best-effort; never block playback
        log.debug("metadata lookup failed for %s", key, exc_info=True)
        meta = dict(_EMPTY_META)
    if len(_META_CACHE) >= _META_CACHE_MAX:
        _META_CACHE.clear()
    _META_CACHE[key] = meta
    return meta


@router.get("/cast")
async def get_cast_status(
    op: Annotated[OperatorUser, Depends(require_operator)],
):
    from services.dashboard.discord_cast import cast_status

    return await cast_status(operator_id=str(op.id))


@router.post("/cast")
async def start_player_cast(
    op: Annotated[OperatorUser, Depends(require_operator)],
    channel: str | None = Query(None, description="Optional voice channel override"),
):
    from services.dashboard.discord_cast import start_cast

    try:
        return await start_cast(operator_id=str(op.id), channel_name=channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("cast start failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cast/sync")
async def sync_player_cast(
    op: Annotated[OperatorUser, Depends(require_operator)],
):
    from services.dashboard.discord_cast import sync_cast

    try:
        return await sync_cast(operator_id=str(op.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("cast sync failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/cast")
async def stop_player_cast(
    op: Annotated[OperatorUser, Depends(require_operator)],
):
    from services.dashboard.discord_cast import stop_cast

    return await stop_cast(operator_id=str(op.id))


@router.post("/player/clear")
async def clear_player(
    op: Annotated[OperatorUser, Depends(require_operator)],
):
    from services.dashboard.player import clear_player_and_broadcast

    clear_player_and_broadcast(operator_id=str(op.id))
    return {"ok": True}
