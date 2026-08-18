#!/usr/bin/env python3
"""Live-probe Brat CD + Never Gonna Give You Up against catalog providers.

Walks Wikidata, MusicBrainz, Discogs, and iTunes/Apple Music, writes a tinted
HTML table (player hue 280), and upserts the Postgres graph when a DSN is set.

Usage:
  PYTHONPATH=. MAYA_ONTOLOGY_DSN=postgresql://postgres:postgres@localhost:5432/maya_public \\
    python scripts/catalog_live_probe.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.paths import setup_paths  # noqa: E402

setup_paths()

from maya_graph.music.catalog import map_identity, merge_identity  # noqa: E402
from maya_graph.music.normalize import (  # noqa: E402
    ParsedTrack,
    artist_refs,
    parse_share_path,
    slskd_external_id,
)
from maya_graph.music.primitives import (  # noqa: E402
    DOMAIN,
    EDGE_APPEARS_ON,
    NODE_RECORDING,
    NODE_RELEASE,
    CanonicalWork,
    Recording,
    ResolutionEvent,
    SourceRef,
    WorkQuery,
    DIM_SEMANTIC,
)
from maya_graph.music.schemas import default_catalog_schemas  # noqa: E402
from maya_graph.music.schemas.discogs import USER_AGENT as DISCOGS_UA  # noqa: E402
from maya_graph.music.schemas.itunes import search_album  # noqa: E402
from maya_graph.music.schemas.musicbrainz import USER_AGENT as MB_UA  # noqa: E402
from maya_graph.music.schemas.wikidata import WikidataSchema  # noqa: E402
from maya_graph.projector import link, upsert_node  # noqa: E402

BRAT_CD_PATH = r"Music\Charli XCX\Brat\01 - 360.flac"
NGGYU_PATH = r"Music\Rick Astley\Never Gonna Give You Up 7inch\01 - Never Gonna Give You Up.flac"

# Player-shell tint (docs/content/design/music-player-interface.md --player-hue 280).
TINT_HUE = 280
TINT_BG = f"oklch(0.12 0.02 {TINT_HUE})"
TINT_FG = f"oklch(0.91 0.02 {TINT_HUE})"
TINT_MUTED = f"oklch(0.62 0.04 {TINT_HUE})"
TINT_HEAD = f"oklch(0.22 0.05 {TINT_HUE})"
TINT_ROW = f"oklch(0.16 0.03 {TINT_HUE})"
TINT_ALT = f"oklch(0.18 0.035 {TINT_HUE})"
TINT_ACCENT = f"oklch(0.72 0.12 {TINT_HUE})"
TINT_OK = "oklch(0.72 0.14 150)"
TINT_MISS = "oklch(0.65 0.12 25)"


@dataclass
class ProviderHit:
    provider: str
    ok: bool
    label: str
    artists: str
    work_key: str
    url: str
    extra: str
    error: str = ""
    work: CanonicalWork | None = None


def _artists(work: CanonicalWork) -> str:
    return ", ".join(a.name for a in work.artists) or "—"


def _primary_url(work: CanonicalWork) -> str:
    for anchor in work.anchors:
        if anchor.url:
            return anchor.url
    return ""


def _hit_from_work(provider: str, work: CanonicalWork | None, *, error: str = "") -> ProviderHit:
    if work is None:
        return ProviderHit(provider, False, "—", "—", "—", "", "", error or "no hit")
    extra = work.attrs.get("album") or work.attrs.get("isrc") or work.attrs.get("year") or ""
    ids = ", ".join(f"{a.schema}:{a.external_id}" for a in work.anchors[:4])
    return ProviderHit(
        provider=provider,
        ok=True,
        label=work.label,
        artists=_artists(work),
        work_key=work.key,
        url=_primary_url(work),
        extra=str(extra or ids),
        work=work,
    )


async def _schema_hit(schema, query: WorkQuery) -> ProviderHit:
    name = schema.schema_id
    try:
        works = await schema.search_work(query)
    except Exception as exc:  # noqa: BLE001
        return ProviderHit(name, False, "—", "—", "—", "", "", str(exc)[:160])
    return _hit_from_work(name, works[0] if works else None, error="no hit")


async def _discogs_master(artist: str, release_title: str) -> ProviderHit:
    params = {
        "type": "master",
        "artist": artist,
        "release_title": release_title,
        "per_page": 5,
    }
    headers = {"User-Agent": DISCOGS_UA, "Accept": "application/json"}
    token = os.environ.get("DISCOGS_TOKEN")
    if token:
        headers["Authorization"] = f"Discogs token={token}"
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            resp = await client.get("https://api.discogs.com/database/search", params=params)
            if resp.status_code != 200:
                return ProviderHit("discogs", False, "—", "—", "—", "", "", f"HTTP {resp.status_code}")
            results = resp.json().get("results") or []
    except Exception as exc:  # noqa: BLE001
        return ProviderHit("discogs", False, "—", artist, "—", "", "", str(exc)[:160])
    if not results:
        return ProviderHit("discogs", False, "—", artist, "—", "", "", "no master")
    row = results[0]
    master_id = row.get("id") or row.get("master_id")
    url = f"https://www.discogs.com/master/{master_id}"
    work = CanonicalWork(
        key=f"discogs:master/{master_id}",
        label=str(row.get("title") or release_title),
        artists=artist_refs(artist),
        anchors=(
            SourceRef(schema="discogs", external_id=f"master/{master_id}", url=url),
        ),
        attrs={"kind": "album", "year": row.get("year")},
    )
    return _hit_from_work("discogs", work)


async def _mb_release_group(artist: str, release_title: str) -> ProviderHit:
    query = f'release:"{release_title}" AND artist:"{artist}" AND primarytype:Album'
    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            headers={"User-Agent": MB_UA, "Accept": "application/json"},
        ) as client:
            resp = await client.get(
                "https://musicbrainz.org/ws/2/release-group/",
                params={"query": query, "fmt": "json", "limit": 5},
            )
            if resp.status_code != 200:
                return ProviderHit("mb", False, "—", "—", "—", "", "", f"HTTP {resp.status_code}")
            groups = resp.json().get("release-groups") or []
    except Exception as extra:  # noqa: BLE001
        return ProviderHit("mb", False, "—", artist, "—", "", "", str(extra)[:160])
    if not groups:
        return ProviderHit("mb", False, "—", artist, "—", "", "", "no release-group")
    row = groups[0]
    rgid = row.get("id")
    url = f"https://musicbrainz.org/release-group/{rgid}"
    work = CanonicalWork(
        key=f"mb:release-group/{rgid}",
        label=str(row.get("title") or release_title),
        artists=artist_refs(artist),
        anchors=(
            SourceRef(schema="mb", external_id=f"release-group/{rgid}", url=url),
        ),
        attrs={"kind": "album", "primary_type": row.get("primary-type")},
    )
    return _hit_from_work("mb", work)


def _markdown_table(hits: list[ProviderHit]) -> str:
    lines = [
        "| Provider | Status | Canonical name | Artists | Work key | Link |",
        "|---|---|---|---|---|---|",
    ]
    for hit in hits:
        status = "hit" if hit.ok else "miss"
        name = hit.label.replace("|", "/")
        link = f"[open]({hit.url})" if hit.url else (hit.error or "—")
        lines.append(
            f"| `{hit.provider}` | {status} | {name} | {hit.artists} | `{hit.work_key}` | {link} |"
        )
    return "\n".join(lines)


def _html_table(title: str, hits: list[ProviderHit]) -> str:
    rows = []
    for i, hit in enumerate(hits):
        bg = TINT_ROW if i % 2 == 0 else TINT_ALT
        status_color = TINT_OK if hit.ok else TINT_MISS
        status = "hit" if hit.ok else "miss"
        link = (
            f'<a href="{escape(hit.url)}" style="color:{TINT_ACCENT}">{escape(hit.url)}</a>'
            if hit.url
            else escape(hit.error or "—")
        )
        rows.append(
            f"<tr style='background:{bg}'>"
            f"<td style='padding:10px'><code>{escape(hit.provider)}</code></td>"
            f"<td style='padding:10px;color:{status_color};font-weight:600'>{status}</td>"
            f"<td style='padding:10px'>{escape(hit.label)}</td>"
            f"<td style='padding:10px'>{escape(hit.artists)}</td>"
            f"<td style='padding:10px'><code>{escape(hit.work_key)}</code></td>"
            f"<td style='padding:10px;word-break:break-all'>{link}</td>"
            "</tr>"
        )
    body = "\n".join(rows)
    return f"""
<section style="margin:2rem 0">
  <h2 style="color:{TINT_ACCENT};font-family:ui-sans-serif">{escape(title)}</h2>
  <table style="border-collapse:collapse;width:100%;color:{TINT_FG};font-family:ui-sans-serif;font-size:14px">
    <thead style="background:{TINT_HEAD}">
      <tr>
        <th style="text-align:left;padding:10px">Provider</th>
        <th style="text-align:left;padding:10px">Status</th>
        <th style="text-align:left;padding:10px">Canonical name</th>
        <th style="text-align:left;padding:10px">Artists</th>
        <th style="text-align:left;padding:10px">Work key</th>
        <th style="text-align:left;padding:10px">Link</th>
      </tr>
    </thead>
    <tbody>{body}</tbody>
  </table>
</section>
"""


def _anchor_hits(title: str, work: CanonicalWork) -> list[ProviderHit]:
    hits: list[ProviderHit] = []
    for anchor in work.anchors:
        hits.append(
            ProviderHit(
                provider=anchor.schema,
                ok=True,
                label=work.label,
                artists=_artists(work),
                work_key=anchor.domain_key(),
                url=anchor.url or "",
                extra=title,
                work=work,
            )
        )
    return hits or [
        ProviderHit("graph", False, work.label, _artists(work), work.key, "", "", "no anchors")
    ]


def _album_work(hits: list[ProviderHit], artist: str, title: str) -> CanonicalWork:
    works = [hit.work for hit in hits if hit.ok and hit.work is not None]
    parsed = ParsedTrack(artist=artist, title=title, base_title=title, album=title)
    if works:
        merged = merge_identity(parsed, works)
        if not merged.key.startswith("fp:"):
            attrs = {**merged.attrs, "kind": "album", "format": "CD"}
            return CanonicalWork(
                key=merged.key,
                label=merged.label,
                aliases=merged.aliases,
                anchors=merged.anchors,
                artists=merged.artists or artist_refs(artist),
                attrs=attrs,
            )
    return CanonicalWork(
        key="fp:brat-album",
        label=title,
        artists=artist_refs(artist),
        attrs={"kind": "album", "unmapped": True},
    )


async def probe() -> dict[str, Any]:
    schemas = default_catalog_schemas()
    brat_track = parse_share_path(BRAT_CD_PATH)
    nggyu = parse_share_path(NGGYU_PATH)

    brat_query = WorkQuery(text=brat_track.base_title, artist=brat_track.artist)
    nggyu_query = WorkQuery(text=nggyu.base_title, artist=nggyu.artist)

    brat_track_hits: list[ProviderHit] = []
    nggyu_hits: list[ProviderHit] = []
    for schema in schemas:
        brat_track_hits.append(await _schema_hit(schema, brat_query))
        nggyu_hits.append(await _schema_hit(schema, nggyu_query))

    wd_album = await WikidataSchema().search_release(
        WorkQuery(text="Brat", artist="Charli XCX")
    )
    brat_album_hits = [
        _hit_from_work("wd", wd_album[0] if wd_album else None, error="no album"),
        await _mb_release_group("Charli XCX", "Brat"),
        await _discogs_master("Charli XCX", "Brat"),
    ]
    apple_albums = await search_album("Charli XCX", "Brat")
    brat_album_hits.append(
        _hit_from_work("apple_music", apple_albums[0] if apple_albums else None, error="no album")
    )

    mapped_brat = await map_identity(
        brat_track,
        schemas,
        extra_works=tuple(h.work for h in brat_track_hits if h.work),
    )
    mapped_nggyu = await map_identity(
        nggyu,
        schemas,
        extra_works=tuple(h.work for h in nggyu_hits if h.work),
    )
    mapped_album = _album_work(brat_album_hits, "Charli XCX", "Brat")

    graph: dict[str, Any] = {"wrote": False}
    dsn = os.environ.get("MAYA_ONTOLOGY_DSN")
    if dsn:
        from maya_graph.music.broker import MusicQueryBroker
        from maya_graph.ontology_schema import ensure_ontology_schema

        import asyncpg

        conn = await asyncpg.connect(dsn)
        try:
            await ensure_ontology_schema(conn)
        finally:
            await conn.close()

        broker = MusicQueryBroker(dsn=dsn, schemas=())
        brat_rec = Recording(
            source=SourceRef(
                schema="slskd",
                external_id=slskd_external_id("live-probe", BRAT_CD_PATH, 28_000_000),
            ),
            title=mapped_brat.label,
            attrs={"filename": BRAT_CD_PATH, "album": "Brat", "kind": "cd-track"},
        )
        nggyu_rec = Recording(
            source=SourceRef(
                schema="slskd",
                external_id=slskd_external_id("live-probe", NGGYU_PATH, 12_000_000),
            ),
            title=mapped_nggyu.label,
            attrs={"filename": NGGYU_PATH, "album": nggyu.album, "kind": "seven-inch"},
        )
        brat_id = await broker.ingest(
            ResolutionEvent(mapped_brat, (brat_rec,), "catalog", 0.85)
        )
        nggyu_id = await broker.ingest(
            ResolutionEvent(mapped_nggyu, (nggyu_rec,), "catalog", 0.85)
        )
        album_id = await broker.ingest(
            ResolutionEvent(mapped_album, (), "catalog", 0.85)
        )
        conn = await asyncpg.connect(dsn)
        try:
            release_id = await upsert_node(
                conn,
                domain=DOMAIN,
                domain_id=mapped_album.key,
                node_type=NODE_RELEASE,
                label=mapped_album.label,
                attrs={
                    "kind": "album",
                    "format": "CD",
                    "anchors": [
                        {"schema": a.schema, "external_id": a.external_id, "url": a.url}
                        for a in mapped_album.anchors
                    ],
                },
            )
            rec_id = await conn.fetchval(
                "SELECT id FROM ontology_node WHERE domain=$1 AND domain_id=$2 AND node_type=$3",
                DOMAIN,
                brat_rec.source.domain_key(),
                NODE_RECORDING,
            )
            if rec_id is not None:
                await link(
                    conn,
                    str(rec_id),
                    str(release_id),
                    edge_type=EDGE_APPEARS_ON,
                    dimension=DIM_SEMANTIC,
                    confidence=0.85,
                )
        finally:
            await conn.close()
        graph = {
            "wrote": True,
            "brat_work_key": mapped_brat.key,
            "brat_node_id": brat_id,
            "brat_album_key": mapped_album.key,
            "brat_album_node_id": album_id,
            "brat_release_id": str(release_id),
            "nggyu_work_key": mapped_nggyu.key,
            "nggyu_node_id": nggyu_id,
        }

    mapped_brat_hits = _anchor_hits("Brat 360", mapped_brat)
    mapped_nggyu_hits = _anchor_hits("NGGYU", mapped_nggyu)
    mapped_album_hits = _anchor_hits("Brat CD", mapped_album)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Catalog live probe — hue {TINT_HUE}</title>
  <style>
    :root {{
      --player-hue: {TINT_HUE};
      --player-bg: {TINT_BG};
      --player-fg: {TINT_FG};
      --player-muted: {TINT_MUTED};
      --player-accent: {TINT_ACCENT};
    }}
    body {{ background: var(--player-bg); color: var(--player-fg); padding: 24px; }}
  </style>
</head>
<body>
  <p style="color:{TINT_MUTED}">Player hue tint {TINT_HUE} · Brat CD + Never Gonna Give You Up 7″</p>
  {_html_table('Brat CD — Charli XCX / Brat (album)', brat_album_hits)}
  {_html_table('Brat CD track — 360', brat_track_hits)}
  {_html_table('Never Gonna Give You Up 7″ single', nggyu_hits)}
  {_html_table('Graph anchors — Brat CD album', mapped_album_hits)}
  {_html_table('Graph anchors — 360', mapped_brat_hits)}
  {_html_table('Graph anchors — Never Gonna Give You Up', mapped_nggyu_hits)}
</body>
</html>
"""

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parsed": {
            "brat": {
                "artist": brat_track.artist,
                "title": brat_track.base_title,
                "album": brat_track.album,
            },
            "nggyu": {
                "artist": nggyu.artist,
                "title": nggyu.base_title,
                "album": nggyu.album,
            },
        },
        "mapped": {
            "brat": {
                "key": mapped_brat.key,
                "label": mapped_brat.label,
                "artists": _artists(mapped_brat),
                "anchors": [
                    {"schema": a.schema, "id": a.external_id, "url": a.url}
                    for a in mapped_brat.anchors
                ],
            },
            "brat_album": {
                "key": mapped_album.key,
                "label": mapped_album.label,
                "artists": _artists(mapped_album),
                "anchors": [
                    {"schema": a.schema, "id": a.external_id, "url": a.url}
                    for a in mapped_album.anchors
                ],
            },
            "nggyu": {
                "key": mapped_nggyu.key,
                "label": mapped_nggyu.label,
                "artists": _artists(mapped_nggyu),
                "anchors": [
                    {"schema": a.schema, "id": a.external_id, "url": a.url}
                    for a in mapped_nggyu.anchors
                ],
            },
        },
        "hits": {
            "brat_360": [hit.__dict__ | {"work": None} for hit in brat_track_hits],
            "brat_cd": [hit.__dict__ | {"work": None} for hit in brat_album_hits],
            "nggyu_single": [hit.__dict__ | {"work": None} for hit in nggyu_hits],
        },
        "markdown": {
            "brat_360": _markdown_table(brat_track_hits),
            "brat_cd": _markdown_table(brat_album_hits),
            "nggyu_single": _markdown_table(nggyu_hits),
            "graph_album": _markdown_table(mapped_album_hits),
            "graph_360": _markdown_table(mapped_brat_hits),
            "graph_nggyu": _markdown_table(mapped_nggyu_hits),
        },
        "graph": graph,
        "html": html,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "data" / "slskd"),
        help="Directory for HTML/JSON artifacts",
    )
    args = parser.parse_args()
    payload = asyncio.run(probe())
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "catalog_live_tint.html"
    json_path = out / "catalog_live.json"
    html_path.write_text(payload["html"], encoding="utf-8")
    slim = {k: v for k, v in payload.items() if k != "html"}
    json_path.write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")
    print(f"parsed brat: {payload['parsed']['brat']}")
    print(f"parsed nggyu: {payload['parsed']['nggyu']}")
    print()
    print("## Brat CD (album)")
    print(payload["markdown"]["brat_cd"])
    print()
    print("## Brat CD track — 360")
    print(payload["markdown"]["brat_360"])
    print()
    print("## Never Gonna Give You Up 7″")
    print(payload["markdown"]["nggyu_single"])
    print()
    print("## Graph anchors — Brat CD")
    print(payload["markdown"]["graph_album"])
    print()
    print("## Graph anchors — 360")
    print(payload["markdown"]["graph_360"])
    print()
    print("## Graph anchors — NGGYU")
    print(payload["markdown"]["graph_nggyu"])
    print()
    print(f"mapped brat key: {payload['mapped']['brat']['key']}")
    print(f"mapped brat album key: {payload['mapped']['brat_album']['key']}")
    print(f"mapped nggyu key: {payload['mapped']['nggyu']['key']}")
    print(f"graph: {payload['graph']}")
    print(f"wrote {html_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
