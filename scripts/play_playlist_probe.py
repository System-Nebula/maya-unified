#!/usr/bin/env python3
"""Live-resolve a YouTube / YouTube Music playlist into the sticky player.

Expands playable YouTube URLs, then fans the album out to Apple Music /
Wikidata / MusicBrainz / Discogs and stamps ontology keys onto the tracks.

Usage:
  PYTHONPATH=. python scripts/play_playlist_probe.py
  PYTHONPATH=. python scripts/play_playlist_probe.py --url 'https://youtube.com/playlist?list=…'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.paths import setup_paths  # noqa: E402

setup_paths()

from services.dashboard.player import build_playlist_for_query  # noqa: E402
from services.tracing import attach_in_memory_exporter, corr_span, span_records  # noqa: E402

DEFAULT_URL = (
    "https://youtube.com/playlist?list="
    "OLAK5uy_mcs9iYWN2LEM-J7drMBsjBYJhbmE544rQ"
)

TINT_HUE = 280
TINT_BG = f"oklch(0.12 0.02 {TINT_HUE})"
TINT_FG = f"oklch(0.91 0.02 {TINT_HUE})"
TINT_MUTED = f"oklch(0.62 0.04 {TINT_HUE})"
TINT_HEAD = f"oklch(0.22 0.05 {TINT_HUE})"
TINT_ROW = f"oklch(0.16 0.03 {TINT_HUE})"
TINT_ALT = f"oklch(0.18 0.035 {TINT_HUE})"
TINT_ACCENT = f"oklch(0.72 0.12 {TINT_HUE})"


def _playlist_id(url: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("list") or []
    return values[0] if values else ""


def _platform_cell(track: dict[str, Any]) -> str:
    refs = track.get("source_refs") or []
    bits: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        schema = str(ref.get("schema_id") or "")
        if schema in seen or schema in {"isrc"}:
            continue
        seen.add(schema)
        href = str(ref.get("url") or "")
        label = escape(schema)
        if href:
            bits.append(f'<a href="{escape(href)}" style="color:{TINT_ACCENT}">{label}</a>')
        else:
            bits.append(label)
    return ", ".join(bits) or "—"


def _html(playlist: dict[str, Any], traces: list[dict[str, Any]], url: str) -> str:
    tracks = playlist.get("tracks") or []
    rows: list[str] = []
    for idx, track in enumerate(tracks):
        bg = TINT_ALT if idx % 2 else TINT_ROW
        title = escape(str(track.get("title") or "—"))
        artist = escape(str(track.get("artist") or playlist.get("artist") or "—"))
        work_key = escape(str(track.get("work_key") or "—"))
        yt = str(track.get("query") or "")
        yt_cell = (
            f'<a href="{escape(yt)}" style="color:{TINT_ACCENT}">youtube</a>' if yt else "—"
        )
        rows.append(
            f'<tr style="background:{bg}">'
            f'<td style="padding:10px;color:{TINT_MUTED}">{idx + 1}</td>'
            f'<td style="padding:10px">{title}</td>'
            f'<td style="padding:10px">{artist}</td>'
            f'<td style="padding:10px;font-family:ui-monospace;font-size:12px">{work_key}</td>'
            f'<td style="padding:10px">{yt_cell} · {_platform_cell(track)}</td>'
            "</tr>"
        )
    body = "\n".join(rows) or (
        f'<tr><td colspan="5" style="padding:10px;color:{TINT_MUTED}">no tracks</td></tr>'
    )
    span_rows = []
    for span in traces:
        attrs = span.get("attributes") or {}
        extra = (
            attrs.get("title")
            or attrs.get("track_count")
            or attrs.get("url")
            or ""
        )
        span_rows.append(
            f'<tr style="background:{TINT_ROW}">'
            f'<td style="padding:10px">{escape(str(span.get("name")))}</td>'
            f'<td style="padding:10px;color:{TINT_MUTED}">{span.get("duration_ms")}ms</td>'
            f'<td style="padding:10px;color:{TINT_MUTED}">{escape(str(extra))}</td>'
            "</tr>"
        )
    spans_body = "\n".join(span_rows) or (
        f'<tr><td colspan="3" style="padding:10px;color:{TINT_MUTED}">no spans</td></tr>'
    )
    title = escape(str(playlist.get("title") or "Playlist"))
    artist = escape(str(playlist.get("artist") or "—"))
    work_key = escape(str(playlist.get("work_key") or "—"))
    presentation = escape(str(playlist.get("presentation") or ""))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
</head>
<body style="margin:0;background:{TINT_BG};color:{TINT_FG};font-family:ui-sans-serif">
  <main style="max-width:1100px;margin:0 auto;padding:2rem">
    <p style="color:{TINT_MUTED};letter-spacing:0.08em;font-size:12px">PLAYER HUE {TINT_HUE}</p>
    <h1 style="color:{TINT_ACCENT}">{title}</h1>
    <p style="color:{TINT_MUTED}">{artist} · {work_key} · {len(tracks)} tracks · {presentation}</p>
    <p style="color:{TINT_MUTED}"><a href="{escape(url)}" style="color:{TINT_ACCENT}">{escape(url)}</a></p>
    <table style="border-collapse:collapse;width:100%;font-size:14px">
      <thead style="background:{TINT_HEAD}">
        <tr>
          <th style="text-align:left;padding:10px">#</th>
          <th style="text-align:left;padding:10px">Title</th>
          <th style="text-align:left;padding:10px">Artist</th>
          <th style="text-align:left;padding:10px">Work key</th>
          <th style="text-align:left;padding:10px">Platforms</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
    <h2 style="color:{TINT_ACCENT};margin-top:2.5rem">OTEL spans</h2>
    <table style="border-collapse:collapse;width:100%;font-size:14px">
      <thead style="background:{TINT_HEAD}">
        <tr>
          <th style="text-align:left;padding:10px">Span</th>
          <th style="text-align:left;padding:10px">Duration</th>
          <th style="text-align:left;padding:10px">Attr</th>
        </tr>
      </thead>
      <tbody>{spans_body}</tbody>
    </table>
  </main>
</body>
</html>
"""


async def probe(url: str) -> dict[str, Any]:
    from opentelemetry import trace

    exporter, previous = attach_in_memory_exporter("maya-play-playlist-probe")
    try:
        with corr_span("play.live_probe", url=url, playlist_id=_playlist_id(url)):
            playlist = await build_playlist_for_query(url, ontology_deep=True)
        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
        traces = span_records(exporter)
    finally:
        from services.tracing import restore_tracer_provider

        restore_tracer_provider(previous)

    tracks = playlist.get("tracks") or []
    return {
        "url": url,
        "playlist_id": _playlist_id(url),
        "title": playlist.get("title"),
        "artist": playlist.get("artist"),
        "work_key": playlist.get("work_key"),
        "presentation": playlist.get("presentation"),
        "track_count": len(tracks),
        "source_refs": playlist.get("source_refs") or [],
        "tracks": [
            {
                "title": t.get("title"),
                "artist": t.get("artist"),
                "query": t.get("query"),
                "work_key": t.get("work_key"),
                "source_refs": t.get("source_refs") or [],
            }
            for t in tracks
        ],
        "traces": {
            "service": "maya-play-playlist-probe",
            "span_count": len(traces),
            "spans": traces,
        },
        "html": _html(playlist, traces, url),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "data" / "slskd"),
        help="Directory for HTML/JSON artifacts",
    )
    args = parser.parse_args()
    payload = asyncio.run(probe(args.url))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "play_playlist_tint.html"
    json_path = out / "play_playlist.json"
    traces_path = out / "play_playlist_traces.json"
    html_path.write_text(payload["html"], encoding="utf-8")
    slim = {k: v for k, v in payload.items() if k != "html"}
    json_path.write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")
    traces_path.write_text(json.dumps(payload["traces"], indent=2) + "\n", encoding="utf-8")
    print(f"title: {payload['title']}")
    print(f"artist: {payload.get('artist')}")
    print(f"work_key: {payload.get('work_key')}")
    print(f"presentation: {payload['presentation']}")
    print(f"tracks: {payload['track_count']}")
    print()
    for idx, track in enumerate(payload["tracks"][:20], start=1):
        platforms = ",".join(
            sorted({str(r.get("schema_id")) for r in (track.get("source_refs") or []) if r.get("schema_id")})
        )
        print(
            f"{idx:2}. {track.get('title') or '—'}  "
            f"{track.get('work_key') or '—'}  {platforms}"
        )
    if payload["track_count"] > 20:
        print(f"… {payload['track_count'] - 20} more")
    print()
    traces = payload["traces"]["spans"]
    print(f"## OTEL spans ({len(traces)})")
    for row in traces:
        attrs = row["attributes"]
        extra = (
            attrs.get("ontology.album_key")
            or attrs.get("ontology.artist")
            or attrs.get("title")
            or attrs.get("track_count")
            or attrs.get("url")
            or ""
        )
        print(f"- {row['name']} {row['duration_ms']}ms {extra}".rstrip())
    print()
    print(html_path)
    print(json_path)
    print(traces_path)
    return 0 if payload["track_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
