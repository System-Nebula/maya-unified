"""Search adapter: wrap slskd-api into typed maya-contracts models.

No business logic beyond search + ranking. Uses env vars for config so
the same adapter works in gateway mode and CLI mode.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path, PureWindowsPath
from typing import Any, Optional

from maya_contracts import (
    DownloadRequest,
    DownloadResult,
    DownloadStatus,
    QualityTier,
    SearchHit,
    SearchQuery,
    SearchResult,
    compute_quality_score,
    infer_quality_tier,
)

# ---------------------------------------------------------------------------
# Client bootstrap
# ---------------------------------------------------------------------------

_SLSKD_CLIENT = None

NGGYU_ARTIST = "Rick Astley"
NGGYU_TITLE = "Never Gonna Give You Up"
_SEVEN_INCH_TOKENS = ('7"', "7''", "7inch", "7-inch", "7 inch", "7in")
_TWELVE_INCH_TOKENS = ('12"', "12''", "12inch", "12-inch", "12 inch", "12in")


def reset_client() -> None:
    """Drop the cached slskd client (tests / process reconfig)."""
    global _SLSKD_CLIENT
    _SLSKD_CLIENT = None


def nggyu_7inch_query() -> SearchQuery:
    """Smoke query: Rick Astley — Never Gonna Give You Up, lossless.

    Do not put ``7"`` in the Soulseek search text. slskd keeps those searches
    ``InProgress`` and returns ``fileCount > 0`` with an empty ``responses``
    list, which looks like "no hits". Prefer a 7-inch path client-side after
    FLACs come back.
    """
    return SearchQuery(
        artist=NGGYU_ARTIST,
        title=NGGYU_TITLE,
        exact_phrase=False,
        format_filter=QualityTier.LOSSLESS,
        max_results=50,
    )


def is_seven_inch(filename: str) -> bool:
    lower = filename.lower()
    return any(token in lower for token in _SEVEN_INCH_TOKENS)


def is_twelve_inch(filename: str) -> bool:
    lower = filename.lower()
    return any(token in lower for token in _TWELVE_INCH_TOKENS)


def vinyl_preference(filename: str) -> int:
    """Higher is better: 7-inch, then 12-inch, then other FLACs."""
    if is_seven_inch(filename):
        return 2
    if is_twelve_inch(filename):
        return 1
    return 0


def flac_hits(result: SearchResult) -> list[SearchHit]:
    return [hit for hit in result.hits if hit.extension.lower() == "flac"]


def pick_seven_inch_flac(result: SearchResult) -> SearchHit | None:
    """Prefer a 7\" FLAC, then 12\", then the best remaining FLAC hit."""
    flacs = flac_hits(result)
    if not flacs:
        return None
    return max(flacs, key=lambda hit: (vinyl_preference(hit.filename), hit.quality_score))


def _get_client():
    global _SLSKD_CLIENT
    if _SLSKD_CLIENT is not None:
        return _SLSKD_CLIENT

    from slskd_api import SlskdClient

    host = os.environ.get("SLSKD_HOST", "http://localhost:5030")
    api_key = os.environ.get("SLSKD_API_KEY")
    if not api_key:
        raise RuntimeError("SLSKD_API_KEY is not set (see .env.example)")
    _SLSKD_CLIENT = SlskdClient(host=host, api_key=api_key)
    return _SLSKD_CLIENT


# ---------------------------------------------------------------------------
# Path parsing helpers
# ---------------------------------------------------------------------------

_KNOWN_EXTS = {".flac", ".mp3", ".m4a", ".wav", ".aiff", ".aif", ".ogg", ".opus", ".wma"}


def _parse_filename_hints(path: str) -> dict:
    """Try to extract artist / album / title from a Soulseek share path.

    Typical patterns:
        Music\\Artist\\Album\\01 - Title.flac
        E:\\Music\\Artist\\Album\\Title.mp3
        Downloads\\Artist - Album\\01 Title.flac
    """
    pw = PureWindowsPath(path)
    parts = list(pw.parents)[::-1] if pw.parents else []
    stem = pw.stem

    result: dict[str, Optional[str]] = {
        "artist_hint": None,
        "album_hint": None,
        "title_hint": stem,
    }

    # Walk parents bottom-up, looking for meaningful dir names
    meaningful = [p for p in parts if p.name and p.name not in ("Music", "Downloads", "E:", "F:")]
    if len(meaningful) >= 2:
        result["artist_hint"] = meaningful[-2].name  # second-to-last meaningful dir
        result["album_hint"] = meaningful[-1].name  # immediate parent
    elif len(meaningful) == 1:
        result["album_hint"] = meaningful[-1].name

    # Clean track number prefixes from title
    import re
    match = re.match(r"^(\d+)[\s\.\-_]+(.+)$", stem)
    if match:
        result["title_hint"] = match.group(2).strip()

    return result


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------


def _wait_for_search(client, search_id: str, wait_seconds: int) -> dict:
    """Poll slskd until the search completes or ``wait_seconds`` elapses.

    While a search is ``InProgress``, slskd reports ``fileCount``/``responseCount``
    but leaves ``responses`` empty. A single sleep-then-fetch therefore looks
    like zero hits. ``wait_seconds <= 0`` fetches once (unit tests).
    """
    def _state() -> dict:
        payload = client.searches.state(search_id, includeResponses=True)
        return payload if isinstance(payload, dict) else {}

    if wait_seconds <= 0:
        return _state()

    deadline = time.time() + wait_seconds
    last: dict = {}
    while True:
        last = _state()
        responses = last.get("responses") or []
        if last.get("isComplete"):
            return last
        remaining = deadline - time.time()
        if remaining <= 0:
            if not responses:
                fetch_responses = getattr(client.searches, "search_responses", None)
                if callable(fetch_responses):
                    try:
                        extra = fetch_responses(search_id)
                    except Exception:
                        extra = None
                    if extra:
                        last = dict(last)
                        last["responses"] = extra
            return last
        time.sleep(min(0.5, remaining))


def search_slskd(query: SearchQuery, wait_seconds: int = 15) -> SearchResult:
    """Execute a structured query against Soulseek via slskd.

    Returns typed SearchResult with ranked hits.
    """
    client = _get_client()
    text = query.to_slskd_text()
    t0 = time.time()

    search_kwargs: dict = {}
    if wait_seconds > 0:
        search_kwargs["searchTimeout"] = int(wait_seconds * 1000)
    raw = client.searches.search_text(text, **search_kwargs)

    search_id: str = ""
    if isinstance(raw, dict):
        search_id = raw.get("id", "")
    else:
        search_id = str(raw)

    state = _wait_for_search(client, search_id, wait_seconds)
    responses = state.get("responses", []) if isinstance(state, dict) else []

    # 4. Flatten + type
    hits: list[SearchHit] = []
    for resp in responses:
        username = resp.get("username", "?")
        for f in resp.get("files", []):
            filename: str = f.get("filename", "")
            ext = PureWindowsPath(filename).suffix.lower().lstrip(".")
            size: int = f.get("size", 0)
            is_locked: bool = f.get("isLocked", False)
            has_free: bool = f.get("hasFreeUploadSlot", False)
            queue: int = f.get("queueLength", 0)
            speed: Optional[int] = f.get("uploadSpeed")

            # Extension filter
            if query.format_filter:
                hit_tier = infer_quality_tier(ext, filename)
                # Only keep hits meeting or exceeding the requested tier
                if hit_tier and _tier_rank(hit_tier) < _tier_rank(query.format_filter):
                    continue

            # Size filter
            if query.min_size and size < query.min_size:
                continue
            if query.max_size and size > query.max_size:
                continue

            # User filter
            if query.user and username.lower() != query.user.lower():
                continue

            # Skip locked files
            if is_locked:
                continue

            # Extension filter (basic)
            if ext not in ("flac", "mp3", "m4a", "wav", "aiff", "ogg", "opus"):
                continue

            hints = _parse_filename_hints(filename)
            tier = infer_quality_tier(ext, filename) or QualityTier.UNKNOWN
            score = compute_quality_score(tier, has_free, queue)

            hit = SearchHit(
                username=username,
                filename=filename,
                size=size,
                extension=ext,
                is_locked=is_locked,
                has_free_slot=has_free,
                queue_length=queue,
                upload_speed=speed,
                quality_tier=tier,
                quality_score=score,
                **hints,
            )
            hits.append(hit)

    # 5. Sort by quality score descending
    hits.sort(key=lambda h: h.quality_score, reverse=True)

    elapsed = time.time() - t0
    total = len(hits)

    return SearchResult(
        query=query,
        hits=tuple(hits[: query.max_results]),
        total_hits=total,
        search_id=search_id,
        elapsed_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Download API
# ---------------------------------------------------------------------------

_PLACEHOLDER_TRANSFER_IDS = frozenset({"true", "false", "none", "1", "0"})


def _downloads_dir() -> Path:
    raw = os.environ.get("SLSKD_DOWNLOADS_DIR")
    if raw:
        return Path(raw)
    return Path("data/slskd/downloads")


def _intish(value: Any) -> int | None:
    if value is None or value is False:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_real_transfer_id(transfer_id: str | None) -> bool:
    if not transfer_id:
        return False
    lowered = transfer_id.strip().lower()
    if lowered in _PLACEHOLDER_TRANSFER_IDS:
        return False
    if lowered.startswith("enqueued:"):
        return False
    return True


def _transfer_failed(state: str) -> bool:
    lower = (state or "").lower()
    return any(
        token in lower
        for token in ("errored", "cancelled", "canceled", "timedout", "timed out", "rejected")
    )


def _transfer_succeeded(state: str) -> bool:
    if _transfer_failed(state):
        return False
    lower = (state or "").lower()
    return "succeeded" in lower or "completed" in lower


def iter_transfer_files(downloads: list[dict] | None) -> list[dict[str, Any]]:
    """Flatten slskd `get_all_downloads` payloads into per-file dicts."""
    files: list[dict[str, Any]] = []
    for user_dl in downloads or []:
        if not isinstance(user_dl, dict):
            continue
        username = str(user_dl.get("username") or "")
        directories = user_dl.get("directories")
        nested: list[Any] = []
        if isinstance(directories, list) and directories:
            for directory in directories:
                if isinstance(directory, dict):
                    nested.extend(directory.get("files") or [])
        else:
            nested = list(user_dl.get("files") or [])
        for item in nested:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if username and not row.get("username"):
                row["username"] = username
            files.append(row)
    return files


def find_transfer_file(
    downloads: list[dict] | None,
    *,
    username: str,
    filename: str,
    size: int | None = None,
    transfer_id: str | None = None,
) -> dict[str, Any] | None:
    files = iter_transfer_files(downloads)
    if _is_real_transfer_id(transfer_id):
        for row in files:
            if str(row.get("id") or "") == str(transfer_id):
                return row
    want_name = filename.replace("/", "\\")
    want_base = PureWindowsPath(filename).name.lower()
    matches: list[dict[str, Any]] = []
    for row in files:
        row_user = str(row.get("username") or "")
        if username and row_user and row_user.lower() != username.lower():
            continue
        row_name = str(row.get("filename") or "")
        if row_name.replace("/", "\\") == want_name:
            matches.append(row)
            continue
        if PureWindowsPath(row_name).name.lower() == want_base:
            matches.append(row)
    if size is not None:
        sized = [row for row in matches if _intish(row.get("size")) == size]
        if sized:
            matches = sized
    return matches[-1] if matches else None


def resolve_local_download(filename: str, expected_size: int | None) -> tuple[str | None, int | None]:
    """Locate a completed file under the slskd downloads directory, if present."""
    root = _downloads_dir()
    if not root.is_dir():
        return None, None
    parts = [
        part
        for part in PureWindowsPath(filename).parts
        if part not in {"\\", "/"} and ":" not in part
    ]
    candidates: list[Path] = []
    if parts:
        direct = root.joinpath(*parts)
        if direct.is_file():
            candidates.append(direct)
        named = root / parts[-1]
        if named.is_file() and named not in candidates:
            candidates.append(named)
    base = PureWindowsPath(filename).name
    if base:
        try:
            for path in root.rglob(base):
                if path.is_file() and path not in candidates:
                    candidates.append(path)
        except OSError:
            pass
    if not candidates:
        return None, None
    for path in candidates:
        local_size = path.stat().st_size
        if expected_size is not None and local_size == expected_size:
            return str(path), local_size
    path = candidates[0]
    return str(path), path.stat().st_size


def verify_transfer_file(
    file_row: dict[str, Any],
    expected_size: int,
) -> tuple[bool, str | None, str | None, int | None]:
    """Check transfer success + size. Local file size is required only if the file exists."""
    state = str(file_row.get("state") or "")
    size = _intish(file_row.get("size"))
    transferred = _intish(file_row.get("bytesTransferred"))
    if transferred is None:
        transferred = _intish(file_row.get("bytes_transferred"))
    if _transfer_failed(state):
        return False, f"transfer failed: {state or 'unknown'}", None, None
    if not _transfer_succeeded(state):
        return False, f"transfer not complete: {state or 'unknown'}", None, None
    if expected_size and size is not None and size != expected_size:
        return False, f"transfer size {size} != expected {expected_size}", None, None
    if expected_size and transferred is not None and transferred != expected_size:
        return False, f"bytesTransferred {transferred} != expected {expected_size}", None, None
    if size is not None and transferred is not None and transferred != size:
        return False, f"bytesTransferred {transferred} != size {size}", None, None
    filename = str(file_row.get("filename") or "")
    local_path, local_size = resolve_local_download(filename, expected_size or size)
    want = expected_size or size
    if local_path is not None and local_size is not None and want is not None and local_size != want:
        return False, f"local file size {local_size} != expected {want}", local_path, local_size
    return True, None, local_path, local_size


def _file_complete_event(filename: str) -> bool | None:
    """True if slskd recorded DownloadFileComplete for this file; None if events are unavailable."""
    client = _get_client()
    events_api = getattr(client, "events", None)
    getter = getattr(events_api, "get", None) if events_api is not None else None
    if not callable(getter):
        return None
    try:
        events = getter()
    except Exception:
        return None
    if not events:
        return False
    base = PureWindowsPath(filename).name
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "DownloadFileComplete":
            continue
        blob = event.get("data") or ""
        parsed: Any = blob
        if isinstance(blob, str):
            if filename in blob or (base and base in blob):
                return True
            try:
                parsed = json.loads(blob)
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            name = str(parsed.get("filename") or parsed.get("localPath") or "")
            if name == filename or (base and PureWindowsPath(name).name == base):
                return True
    return False


def wait_for_transfer(
    *,
    username: str,
    filename: str,
    size: int,
    transfer_id: str | None = None,
    wait_seconds: int = 15,
) -> dict[str, Any] | None:
    """Poll slskd until the transfer is terminal or ``wait_seconds`` elapses."""
    client = _get_client()

    def _snapshot() -> dict[str, Any] | None:
        downloads = client.transfers.get_all_downloads()
        return find_transfer_file(
            downloads if isinstance(downloads, list) else [],
            username=username,
            filename=filename,
            size=size,
            transfer_id=transfer_id,
        )

    if wait_seconds <= 0:
        return _snapshot()

    deadline = time.time() + wait_seconds
    last: dict[str, Any] | None = None
    while True:
        last = _snapshot()
        if last is not None:
            state = str(last.get("state") or "")
            if _transfer_succeeded(state) or _transfer_failed(state):
                return last
        remaining = deadline - time.time()
        if remaining <= 0:
            return last
        time.sleep(min(0.5, remaining))


def _extract_enqueue_id(result: Any) -> str | None:
    if result is False or result is None:
        return None
    if isinstance(result, dict):
        raw = result.get("id")
        return str(raw) if raw else None
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict) and first.get("id"):
            return str(first["id"])
        return str(first)
    if result is True:
        return None
    text = str(result).strip()
    return text or None


def _schedule_ingest(
    *,
    username: str,
    filename: str,
    size: int,
    bytes_transferred: int | None,
    local_path: str | None,
) -> None:
    hints = _parse_filename_hints(filename)
    try:
        from services.async_bridge import schedule_coro
        from services.music.ontology import ingest_slskd_file

        schedule_coro(
            ingest_slskd_file(
                username=username,
                filename=filename,
                artist_hint=hints.get("artist_hint"),
                title_hint=hints.get("title_hint"),
                attrs={
                    "size": size,
                    "bytes_transferred": bytes_transferred,
                    "verified": True,
                    "local_path": local_path,
                },
            )
        )
    except Exception:  # noqa: BLE001
        pass


def enqueue_download(
    username: str,
    filename: str,
    size: int,
) -> str | None:
    """Enqueue a single file download on slskd.

    Returns a transfer ID when slskd reports one, otherwise a lookup key.
    Does not ingest into the ontology — wait until the file is verified.
    """
    client = _get_client()
    payload = [
        {
            "filename": filename,
            "size": size,
            "startOffset": 0,
        }
    ]
    try:
        result = client.transfers.enqueue(username, payload)
    except Exception:
        return None
    if result is False:
        return None
    transfer_id = _extract_enqueue_id(result)
    try:
        downloads = client.transfers.get_all_downloads()
        row = find_transfer_file(
            downloads if isinstance(downloads, list) else [],
            username=username,
            filename=filename,
            size=size,
            transfer_id=transfer_id,
        )
        if row and row.get("id"):
            transfer_id = str(row["id"])
    except Exception:
        pass
    if _is_real_transfer_id(transfer_id):
        return transfer_id
    return f"enqueued:{username}:{PureWindowsPath(filename).name}"


def get_downloads() -> list[dict]:
    """Return all current downloads from slskd."""
    client = _get_client()
    return client.transfers.get_all_downloads()


def run_download(req: DownloadRequest) -> DownloadResult:
    """Enqueue a hit, optionally wait until complete, then verify size (and local file if present)."""
    expected = req.hit.size
    transfer_id = enqueue_download(req.hit.username, req.hit.filename, expected)
    if transfer_id is None:
        return DownloadResult(
            request=req,
            status=DownloadStatus.FAILED,
            error="Failed to enqueue download on slskd",
            expected_size=expected,
            verified=False,
        )

    reported_id = transfer_id if _is_real_transfer_id(transfer_id) else None
    s3_key = req.build_s3_key()
    if req.wait_seconds <= 0:
        return DownloadResult(
            request=req,
            status=DownloadStatus.ENQUEUED,
            slskd_transfer_id=reported_id or transfer_id,
            s3_key=s3_key,
            expected_size=expected,
            verified=False,
        )

    row = wait_for_transfer(
        username=req.hit.username,
        filename=req.hit.filename,
        size=expected,
        transfer_id=reported_id,
        wait_seconds=req.wait_seconds,
    )
    if row is None:
        return DownloadResult(
            request=req,
            status=DownloadStatus.FAILED,
            slskd_transfer_id=reported_id,
            s3_key=s3_key,
            expected_size=expected,
            verified=False,
            error=f"download did not appear within {req.wait_seconds}s",
        )

    tid = str(row.get("id") or reported_id or transfer_id)
    transferred = _intish(row.get("bytesTransferred"))
    if transferred is None:
        transferred = _intish(row.get("bytes_transferred"))
    verified, error, local_path, local_size = verify_transfer_file(row, expected)
    state = str(row.get("state") or "")
    if verified:
        _schedule_ingest(
            username=req.hit.username,
            filename=req.hit.filename,
            size=expected,
            bytes_transferred=transferred,
            local_path=local_path,
        )
        return DownloadResult(
            request=req,
            status=DownloadStatus.COMPLETED,
            slskd_transfer_id=tid if _is_real_transfer_id(tid) else reported_id,
            s3_key=s3_key,
            expected_size=expected,
            bytes_transferred=transferred,
            local_path=local_path,
            local_size=local_size,
            verified=True,
        )

    status = DownloadStatus.FAILED
    if not _transfer_failed(state) and not _transfer_succeeded(state):
        status = DownloadStatus.DOWNLOADING
        error = error or f"download did not complete within {req.wait_seconds}s ({state or 'unknown'})"
    return DownloadResult(
        request=req,
        status=status,
        slskd_transfer_id=tid if _is_real_transfer_id(tid) else reported_id,
        s3_key=s3_key,
        expected_size=expected,
        bytes_transferred=transferred,
        local_path=local_path,
        local_size=local_size,
        verified=False,
        error=error,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tier_rank(tier: QualityTier) -> int:
    """Higher = better."""
    ranks = {
        QualityTier.LOSSLESS_24BIT: 100,
        QualityTier.LOSSLESS: 90,
        QualityTier.LOSSLESS_CD: 85,
        QualityTier.HIGH: 60,
        QualityTier.STANDARD: 45,
        QualityTier.AAC_256: 40,
        QualityTier.LOW: 20,
        QualityTier.UNKNOWN: 10,
    }
    return ranks.get(tier, 10)
