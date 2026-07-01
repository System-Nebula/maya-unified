"""Parse a free-text channel input into a :class:`ResolvedChannelPreview`.

v1 is pure-string parsing: no network fetch, no platform API calls. The
Following panel's "+ Add person" modal uses this to render an instant
preview ("This looks like a YouTube channel: @MissKatie") before the
operator commits.

When the enrichment worker ships, it will replace this with a real
metadata lookup (subscriber counts, etc.) — but the contract surface
(:class:`ResolveChannelResponse`) is already wired with
``cross_platform_candidates`` so the matcher slot doesn't require a
contract change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from maya_contracts import (
    Platform,
    ResolveChannelRequest,
    ResolveChannelResponse,
    ResolvedChannelPreview,
)

_YT_CHANNEL_ID_RE = re.compile(r"(UC[A-Za-z0-9_-]{22})")
_YT_HANDLE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?youtube\.com/@([A-Za-z0-9._-]+)"
)
_YT_CHANNEL_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"
)
_YT_PREFIX_RE = re.compile(r"^yt[:/](.+)$", re.IGNORECASE)

_IG_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?"
)
_IG_PREFIX_RE = re.compile(r"^ig[:/](.+)$", re.IGNORECASE)

_TT_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?tiktok\.com/@([A-Za-z0-9._-]+)"
)
_TT_PREFIX_RE = re.compile(r"^tt[:/](.+)$", re.IGNORECASE)

_RSS_PREFIX_RE = re.compile(r"^rss[:/](.+)$", re.IGNORECASE)
_RSS_URL_RE = re.compile(
    r"^https?://[^\s]+(?:/feed/?|\.xml(?:\?|$))(?:\S*)?$",
    re.IGNORECASE,
)


_YT_ATOM = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


@dataclass(frozen=True)
class _ResolutionError(Exception):
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def resolve(req: ResolveChannelRequest) -> ResolveChannelResponse:
    """Best-effort parse the operator's input into a channel preview.

    Raises ValueError if the input doesn't match any known shape and no
    `hint_platform` was supplied.
    """

    text = req.input.strip()
    if not text:
        raise ValueError("input is empty")

    preview = (
        _try_youtube(text)
        or _try_instagram(text)
        or _try_tiktok(text)
        or _try_rss(text)
        or _try_hint(text, req.hint_platform)
    )
    if preview is None:
        raise ValueError(f"could not parse channel input: {req.input!r}")

    return ResolveChannelResponse(
        channel=preview,
        suggested_person_id=None,
        cross_platform_candidates=[],
    )


def _try_youtube(text: str) -> Optional[ResolvedChannelPreview]:
    # 1. yt: prefix shorthand wins outright.
    prefix = _YT_PREFIX_RE.match(text)
    if prefix:
        inner = prefix.group(1).strip()
        if _YT_CHANNEL_ID_RE.fullmatch(inner):
            return _yt_channel_preview(inner, handle=inner)
        return _yt_handle_preview(inner)

    # 2. /channel/UC… URLs and bare UC… IDs.
    m = _YT_CHANNEL_URL_RE.search(text)
    if m:
        cid = m.group(1)
        return _yt_channel_preview(cid, handle=cid)
    if _YT_CHANNEL_ID_RE.fullmatch(text):
        return _yt_channel_preview(text, handle=text)

    # 3. /@handle URLs.
    h = _YT_HANDLE_URL_RE.search(text)
    if h:
        return _yt_handle_preview(h.group(1))

    return None


def _yt_channel_preview(channel_id: str, *, handle: str) -> ResolvedChannelPreview:
    return ResolvedChannelPreview(
        platform=Platform.YOUTUBE,
        platform_id=channel_id,
        handle=handle,
        display_name=handle,
        feed_url=_YT_ATOM.format(channel_id=channel_id),
    )


def _yt_handle_preview(handle: str) -> ResolvedChannelPreview:
    """Handle-only YT input. We don't know the UC… channel_id yet, so we
    stash the handle in both fields; the enrichment worker resolves it
    later. ``feed_url`` is left None — no Atom feed without the channel id.
    """
    norm = handle.lstrip("@")
    return ResolvedChannelPreview(
        platform=Platform.YOUTUBE,
        platform_id=f"@{norm}",
        handle=f"@{norm}",
        display_name=norm,
        feed_url=None,
    )


def _try_instagram(text: str) -> Optional[ResolvedChannelPreview]:
    prefix = _IG_PREFIX_RE.match(text)
    if prefix:
        return _ig_preview(prefix.group(1))
    m = _IG_URL_RE.search(text)
    if m:
        return _ig_preview(m.group(1))
    return None


def _ig_preview(handle: str) -> ResolvedChannelPreview:
    norm = handle.lstrip("@").strip("/")
    return ResolvedChannelPreview(
        platform=Platform.INSTAGRAM,
        platform_id=norm,
        handle=f"@{norm}",
        display_name=norm,
        feed_url=None,
    )


def _try_tiktok(text: str) -> Optional[ResolvedChannelPreview]:
    prefix = _TT_PREFIX_RE.match(text)
    if prefix:
        return _tt_preview(prefix.group(1))
    m = _TT_URL_RE.search(text)
    if m:
        return _tt_preview(m.group(1))
    return None


def _tt_preview(handle: str) -> ResolvedChannelPreview:
    norm = handle.lstrip("@")
    return ResolvedChannelPreview(
        platform=Platform.TIKTOK,
        platform_id=norm,
        handle=f"@{norm}",
        display_name=norm,
        feed_url=None,
    )


def _try_rss(text: str) -> Optional[ResolvedChannelPreview]:
    prefix = _RSS_PREFIX_RE.match(text)
    if prefix:
        return _rss_preview(prefix.group(1).strip())
    if _RSS_URL_RE.match(text):
        return _rss_preview(text)
    return None


def _rss_preview(feed_url: str) -> ResolvedChannelPreview:
    url = feed_url.rstrip("/")
    if not url.endswith("/feed"):
        if url.endswith(".xml"):
            pass
        elif "/feed/" not in url and not url.endswith(".xml"):
            url = f"{url}/feed"
    return ResolvedChannelPreview(
        platform=Platform.RSS,
        platform_id=url,
        handle=url,
        display_name=f"RSS {url}",
        feed_url=url,
    )


def _try_hint(text: str, hint: Optional[Platform]) -> Optional[ResolvedChannelPreview]:
    if hint is None:
        return None
    cleaned = text.lstrip("@").strip("/")
    if hint == Platform.YOUTUBE:
        if _YT_CHANNEL_ID_RE.fullmatch(cleaned):
            return _yt_channel_preview(cleaned, handle=cleaned)
        return _yt_handle_preview(cleaned)
    if hint == Platform.INSTAGRAM:
        return _ig_preview(cleaned)
    if hint == Platform.TIKTOK:
        return _tt_preview(cleaned)
    if hint == Platform.RSS:
        return _rss_preview(text if text.startswith("http") else f"https://{cleaned}")
    return None
