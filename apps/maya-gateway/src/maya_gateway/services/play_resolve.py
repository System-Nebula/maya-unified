"""Resolve free-text `/play` queries against the public demo catalog.

v1 is intentionally tiny: a hand-curated list of public-safe demo tracks plus
a forgiving fuzzy match so users can type things like ``risk astley - never
going to give you up`` and still land on the canonical entry. Future versions
will delegate to the private ontology / enrichment stack.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from maya_contracts import (
    DiscogsRef,
    MatchedVia,
    PlayResolveRequest,
    PlayResolveResponse,
    TrackInfo,
    VideoRef,
)

from maya_gateway.services.discogs import DiscogsClient, default_client

# Public-safe substitute clip. The bundled file under apps/homepage/public/demo
# is a short CC0 sample; production deployments override via env if needed.
DEMO_PREVIEW = "/demo/rick-roll-preview.mp3"


def _youtube_embed(video_id: str) -> str:
    """Build a YouTube IFrame API embed URL.

    Plain ``youtube.com/embed`` (not -nocookie) plus ``enablejsapi=1`` so the
    RadioPlayer can listen for ``onError`` and gracefully fall back when the
    uploader has disabled embedding (error 101/150).
    """
    return (
        f"https://www.youtube.com/embed/{video_id}"
        f"?enablejsapi=1&modestbranding=1&rel=0&playsinline=1"
    )


def _youtube_watch(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


def _youtube_thumb(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


@dataclass(frozen=True)
class DemoTrack:
    track_id: str
    title: str
    artist: str
    album: str | None = None
    duration_seconds: float | None = None
    preview_url: str | None = DEMO_PREVIEW
    artwork_url: str | None = None
    stream_url: str | None = None
    watch_url: str | None = None
    # Optional Discogs master ID — the resolver will enrich the response with
    # videos[] harvested from the Discogs property graph for this master.
    discogs_master_id: int | None = None

    def to_info(self) -> TrackInfo:
        return TrackInfo(
            track_id=self.track_id,
            title=self.title,
            artist=self.artist,
            album=self.album,
            duration_seconds=self.duration_seconds,
            preview_url=self.preview_url,
            artwork_url=self.artwork_url,
            stream_url=self.stream_url,
            watch_url=self.watch_url,
        )


def _yt_track(
    *,
    track_id: str,
    title: str,
    artist: str,
    album: str | None,
    duration_seconds: float | None,
    video_id: str,
    discogs_master_id: int | None = None,
) -> DemoTrack:
    """Build a YouTube-backed demo track in one place."""
    return DemoTrack(
        track_id=track_id,
        title=title,
        artist=artist,
        album=album,
        duration_seconds=duration_seconds,
        preview_url=None,
        artwork_url=_youtube_thumb(video_id),
        stream_url=_youtube_embed(video_id),
        watch_url=_youtube_watch(video_id),
        discogs_master_id=discogs_master_id,
    )


# Public YouTube IDs only — widely-known, publicly-uploaded videos. Some
# (notably the canonical Rick Astley clip) have embedding disabled by the
# uploader; the RadioPlayer detects that and falls back to ``watch_url``.
DEMO_CATALOG: tuple[DemoTrack, ...] = (
    _yt_track(
        track_id="demo:rick-astley:never-gonna-give-you-up",
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        album="Whenever You Need Somebody",
        duration_seconds=213.0,
        video_id="dQw4w9WgXcQ",
        discogs_master_id=96559,
    ),
    _yt_track(
        track_id="demo:nujabes:departure",
        title="Departure",
        artist="Nujabes",
        album="Modal Soul",
        duration_seconds=255.0,
        video_id="WrO9PTpuSSs",
    ),
    _yt_track(
        track_id="demo:aphex-twin:xtal",
        title="Xtal",
        artist="Aphex Twin",
        album="Selected Ambient Works 85-92",
        duration_seconds=295.0,
        video_id="ARE2bxKxXrI",
    ),
    _yt_track(
        track_id="demo:lofi:focus-loop",
        title="Lofi hip hop radio — beats to relax/study to",
        artist="Lofi Girl",
        album="Lofi Radio",
        duration_seconds=None,
        video_id="jfKfPfyJRdk",
    ),
    _yt_track(
        track_id="dnb:ivy-little-sound:cant-love-me",
        title="Can't Love Me",
        artist="[IVY] & A Little Sound",
        album="UKF Drum & Bass",
        duration_seconds=210.0,
        video_id="4waehYAY6qM",
    ),
)


_SPLIT_RE = re.compile(r"\s+[-–—:]\s+")
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text.strip().lower())


def _parse_artist_title(query: str) -> tuple[str | None, str]:
    """Split ``artist - title`` on common delimiters; fall back to whole query."""
    parts = _SPLIT_RE.split(query, maxsplit=1)
    if len(parts) == 2:
        artist, title = parts
        return _normalize(artist), _normalize(title)
    return None, _normalize(query)


def _score(track: DemoTrack, artist: str | None, title: str) -> float:
    """Combined ratio of artist + title similarity (0..1)."""
    haystack_title = _normalize(track.title)
    title_ratio = difflib.SequenceMatcher(None, title, haystack_title).ratio()

    if artist:
        haystack_artist = _normalize(track.artist)
        artist_ratio = difflib.SequenceMatcher(None, artist, haystack_artist).ratio()
        return 0.6 * title_ratio + 0.4 * artist_ratio

    combined = f"{_normalize(track.artist)} {haystack_title}"
    return difflib.SequenceMatcher(None, title, combined).ratio()


def _enrich(track: TrackInfo, demo: DemoTrack, discogs: DiscogsClient | None) -> TrackInfo:
    """Hydrate a matched TrackInfo with ontology data from Discogs."""
    master_id = demo.discogs_master_id
    if master_id is None or discogs is None:
        return track

    master = discogs.fetch_master(master_id)
    if master is None:
        # Network failure or missing — keep our seed values but still pin the
        # Discogs reference so the UI can link out.
        return track.model_copy(
            update={
                "discogs": DiscogsRef(
                    master_id=master_id,
                    url=f"https://www.discogs.com/master/{master_id}",
                )
            }
        )

    return track.model_copy(
        update={
            "videos": master.videos,
            "discogs": master.ref(),
        }
    )


def resolve(
    req: PlayResolveRequest,
    catalog: Iterable[DemoTrack] = DEMO_CATALOG,
    *,
    discogs: Optional[DiscogsClient] = None,
) -> PlayResolveResponse:
    """Score every demo track, return the best match, and enrich it.

    Pass an explicit ``discogs`` client to override the process default (the
    test suite injects a stub so unit tests don't touch the network).
    """
    artist, title = _parse_artist_title(req.query)
    candidates = list(catalog)

    scored = sorted(
        ((_score(t, artist, title), t) for t in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )

    if not scored:
        return PlayResolveResponse(
            matched_via="demo_catalog",
            query=req.query,
            zone=req.zone,
            tracks=[],
            explanation="empty catalog",
        )

    best_score, best = scored[0]
    matched_via: MatchedVia = "exact" if best_score >= 0.95 else "fuzzy"

    client = discogs if discogs is not None else default_client()
    top = _enrich(best.to_info(), best, client)
    runners = [t.to_info() for score, t in scored[1:3] if score >= 0.45]

    return PlayResolveResponse(
        matched_via=matched_via,
        query=req.query,
        zone=req.zone,
        tracks=[top, *runners],
        explanation=f"matched {best.artist} — {best.title} (score={best_score:.2f})",
    )
