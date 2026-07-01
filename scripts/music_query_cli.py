#!/usr/bin/env python3
"""Music query CLI — search Soulseek, download, inspect status.

Two modes:
  1. Direct (default) — talks to slskd API directly. Requires SLSKD_HOST + SLSKD_API_KEY.
  2. Gateway — talks to maya-gateway REST API. Requires MAYA_GATEWAY_URL.

Usage:
  music_query search "artist album"                     direct search
  music_query search --artist "Taylor" --album "Showgirl"  structured search
  music_query search --jsonl                             machine-readable output
  music_query download <username> <filename> <size>      enqueue download
  music_query status                                     list transfers
  music_query search --gateway http://localhost:8080      via gateway API
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Direct-mode imports (optional — only needed when not using --gateway)
# ---------------------------------------------------------------------------

HAS_SLSKD = False
try:
    from slskd_api import SlskdClient
    HAS_SLSKD = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Contract imports
# ---------------------------------------------------------------------------

try:
    from maya_contracts import (
        SearchHit,
        SearchQuery,
        SearchResult,
        AcquisitionRequest,
        AcquisitionResult,
        AcquisitionStatus,
        QualityTier,
        compute_quality_score,
        infer_quality_tier,
    )
    HAS_CONTRACTS = True
except ImportError:
    HAS_CONTRACTS = False


# ---------------------------------------------------------------------------
# Direct slskd client
# ---------------------------------------------------------------------------

def _direct_client() -> Any:
    if not HAS_SLSKD:
        print("error: slskd-api not installed. Install with: uv pip install slskd-api", file=sys.stderr)
        sys.exit(1)
    host = os.environ.get("SLSKD_HOST", "http://localhost:5030")
    key = os.environ.get("SLSKD_API_KEY")
    if not key:
        print("error: SLSKD_API_KEY is not set (see .env.example)", file=sys.stderr)
        sys.exit(1)
    return SlskdClient(host=host, api_key=key)


def _direct_search(args: argparse.Namespace) -> None:
    client = _direct_client()
    # Build query text
    query_parts = []
    if args.artist:
        query_parts.append(args.artist)
    if args.album:
        query_parts.append(args.album)
    if args.title:
        query_parts.append(args.title)
    if args.query:
        query_parts.append(args.query)
    query_text = " ".join(query_parts)

    if args.exact:
        query_text = f'"{query_text}"'

    print(f"Searching: {query_text}", file=sys.stderr)
    t0 = time.time()

    raw = client.searches.search_text(query_text)
    search_id = raw.get("id", "") if isinstance(raw, dict) else str(raw)

    wait = args.wait or 15
    print(f"  waiting {wait}s...", file=sys.stderr)
    time.sleep(wait)

    state = client.searches.state(search_id, includeResponses=True)
    responses = state.get("responses", []) if isinstance(state, dict) else []

    hits = []
    for resp in responses:
        username = resp.get("username", "?")
        for f in resp.get("files", []):
            filename: str = f.get("filename", "")
            ext = Path(filename).suffix.lower().lstrip(".")
            size: int = f.get("size", 0)
            has_free: bool = f.get("hasFreeUploadSlot", False)
            queue: int = f.get("queueLength", 0)

            if ext not in ("flac", "mp3", "m4a", "wav", "aiff", "ogg", "opus"):
                continue
            if f.get("isLocked"):
                continue

            tier = infer_quality_tier(ext, filename) if HAS_CONTRACTS else "?"
            score = compute_quality_score(tier, has_free, queue) if HAS_CONTRACTS else 0.0

            hits.append({
                "username": username,
                "filename": filename,
                "size": size,
                "ext": ext,
                "tier": tier.value if isinstance(tier, QualityTier) else tier,
                "score": round(score, 1),
                "free": has_free,
                "queue": queue,
            })

    hits.sort(key=lambda h: h["score"], reverse=True)

    if args.jsonl:
        for h in hits:
            print(json.dumps(h))
    else:
        print(f"\nFound {len(hits)} files in {time.time()-t0:.1f}s\n")
        for i, h in enumerate(hits[: args.limit or 30], 1):
            free_mark = " FREE" if h["free"] else ""
            print(f"  {i:3d}. [{h['tier']:15s}] score={h['score']:4.1f}{free_mark} queue={h['queue']}")
            print(f"       {h['username']}: {h['filename'][:120]}")


# ---------------------------------------------------------------------------
# Gateway mode
# ---------------------------------------------------------------------------

def _gateway_search(args: argparse.Namespace) -> None:
    import httpx

    base = args.gateway or os.environ.get("MAYA_GATEWAY_URL", "http://localhost:8080")
    query = SearchQuery(
        artist=args.artist,
        album=args.album,
        title=args.title,
        exact_phrase=args.exact,
    )
    r = httpx.post(f"{base}/api/music/query/search", json=query.model_dump(), timeout=60)
    r.raise_for_status()
    result = SearchResult(**r.json())

    if args.jsonl:
        for h in result.hits:
            print(json.dumps(h.model_dump()))
    else:
        best = result.best()
        print(f"\nSearch [{result.search_id[:8]}] — {result.total_hits} hits in {result.elapsed_seconds:.1f}s")
        if best:
            print(f"BEST: [{best.quality_tier.value}] score={best.quality_score:.1f}  {best.username}: {best.filename[:100]}")
        print()
        for i, h in enumerate(result.hits[: args.limit or 30], 1):
            print(f"  {i:3d}. [{h.quality_tier.value:15s}] score={h.quality_score:4.1f}")
            print(f"       {h.username}: {h.filename[:120]}")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _direct_download(args: argparse.Namespace) -> None:
    client = _direct_client()
    payload = [{"filename": args.filename, "size": args.size, "startOffset": 0}]
    try:
        result = client.transfers.enqueue(args.username, payload)
        transfer_id = result.get("id", "?") if isinstance(result, dict) else str(result)
        print(f"Enqueued. Transfer ID: {transfer_id}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def _gateway_download(args: argparse.Namespace) -> None:
    import httpx

    base = args.gateway or os.environ.get("MAYA_GATEWAY_URL", "http://localhost:8080")
    hit = SearchHit(
        username=args.username,
        filename=args.filename,
        size=args.size,
        extension=Path(args.filename).suffix.lower().lstrip("."),
    )
    req = AcquisitionRequest(hit=hit)
    r = httpx.post(f"{base}/api/music/query/download", json=req.model_dump(), timeout=30)
    r.raise_for_status()
    result = AcquisitionResult(**r.json())
    print(f"Status: {result.status.value}")
    if result.slskd_transfer_id:
        print(f"Transfer: {result.slskd_transfer_id}")
    if result.s3_key:
        print(f"S3 key:  {result.s3_key}")
    if result.error:
        print(f"Error:   {result.error}")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def _direct_status(args: argparse.Namespace) -> None:
    client = _direct_client()
    downloads = client.transfers.get_all_downloads()
    if not downloads:
        print("No active downloads")
        return
    for ud in downloads:
        user = ud.get("username", "?")
        for d in ud.get("directories", []):
            for f in d.get("files", []):
                state = f.get("stateDescription", "?")
                pct = f.get("percentComplete", 0)
                fn = Path(f.get("filename", "")).name
                print(f"{user}: {fn}  [{state}] {pct:.0f}%")


def _gateway_status(args: argparse.Namespace) -> None:
    import httpx
    base = args.gateway or os.environ.get("MAYA_GATEWAY_URL", "http://localhost:8080")
    r = httpx.get(f"{base}/api/music/query/status", timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data:
        print("No active downloads")
        return
    for ud in data:
        user = ud.get("username", "?")
        for d in ud.get("directories", []):
            for f in d.get("files", []):
                state = f.get("stateDescription", "?")
                pct = f.get("percentComplete", 0)
                fn = Path(f.get("filename", "")).name
                print(f"{user}: {fn}  [{state}] {pct:.0f}%")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Music query CLI — search Soulseek, download, inspect status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Global flags
    parser.add_argument("--gateway", help="Use gateway REST API at URL instead of direct slskd")
    parser.add_argument("--jsonl", action="store_true", help="Machine-readable JSONL output")
    parser.add_argument("--limit", type=int, default=30, help="Max results to display")
    parser.add_argument("--wait", type=int, default=15, help="Seconds to wait for search results")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # Search
    sp = sub.add_parser("search", help="Search Soulseek")
    sp.add_argument("query", nargs="?", help="Free-form search query (ignored if structured fields used)")
    sp.add_argument("--artist", help="Artist filter")
    sp.add_argument("--album", help="Album filter")
    sp.add_argument("--title", help="Track title filter")
    sp.add_argument("--exact", action="store_true", default=True, help="Wrap query in quotes (default: on)")
    sp.add_argument("--no-exact", dest="exact", action="store_false", help="Don't wrap in quotes")
    sp.add_argument("--dry-run", action="store_true", help="Show composed query text without searching")
    sp.set_defaults(func=_route_search)

    # Download
    sp = sub.add_parser("download", help="Enqueue a file download")
    sp.add_argument("username", help="Soulseek username")
    sp.add_argument("filename", help="Full Windows-style path to file")
    sp.add_argument("size", type=int, help="File size in bytes")
    sp.set_defaults(func=_route_download)

    # Status
    sp = sub.add_parser("status", help="Show download transfers")
    sp.set_defaults(func=_route_status)

    args = parser.parse_args()

    # Route to direct or gateway mode
    args.func(args)
    return 0


def _route_search(args: argparse.Namespace) -> None:
    # Build query text for dry-run
    query_parts = []
    if args.artist:
        query_parts.append(args.artist)
    if args.album:
        query_parts.append(args.album)
    if args.title:
        query_parts.append(args.title)
    if args.query:
        query_parts.append(args.query)
    query_text = " ".join(query_parts)
    if args.exact:
        query_text = f'"{query_text}"'

    if args.dry_run:
        print(f"Query text: {query_text}")
        return

    if args.gateway:
        _gateway_search(args)
    else:
        _direct_search(args)


def _route_download(args: argparse.Namespace) -> None:
    if args.gateway:
        _gateway_download(args)
    else:
        _direct_download(args)


def _route_status(args: argparse.Namespace) -> None:
    if args.gateway:
        _gateway_status(args)
    else:
        _direct_status(args)


if __name__ == "__main__":
    sys.exit(main())
