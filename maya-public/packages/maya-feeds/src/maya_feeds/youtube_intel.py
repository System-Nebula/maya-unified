"""YouTube video description parser for AI news roundup extraction."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from maya_contracts import IntelItemKind

CHAPTER_RE = re.compile(
    r"^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s+(.+)$",
    re.MULTILINE,
)
URL_RE = re.compile(r"https?://[^\s\)\"<>]+")

_CLASSIFIERS: list[tuple[str, IntelItemKind]] = [
    ("github.com", IntelItemKind.REPO),
    ("arxiv.org", IntelItemKind.PAPER),
    ("huggingface.co", IntelItemKind.MODEL),
    ("research.nvidia.com", IntelItemKind.PAPER),
    ("github.io", IntelItemKind.DEMO),
    ("openai.com", IntelItemKind.PRODUCT),
    ("blog.google", IntelItemKind.PRODUCT),
    ("developer.nvidia.com", IntelItemKind.PRODUCT),
    ("microsoft.com", IntelItemKind.PRODUCT),
    ("microsoft.ai", IntelItemKind.PRODUCT),
]


def timestamp_to_seconds(ts: str) -> int:
    parts = ts.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def decode_youtube_redirect(url: str) -> str:
    if "youtube.com/redirect" not in url:
        return url.rstrip(".,)")
    parsed = urlparse(url)
    q = parse_qs(parsed.query).get("q", [None])[0]
    if q:
        return unquote(q)
    return url.rstrip(".,)")


def normalize_url(url: str) -> str:
    url = decode_youtube_redirect(url.rstrip(".,)"))
    parsed = urlparse(url)
    # Strip trailing slashes and common tracking params for dedup
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


def classify_url(url: str) -> IntelItemKind:
    lower = url.lower()
    for domain, kind in _CLASSIFIERS:
        if domain in lower:
            return kind
    return IntelItemKind.UNKNOWN


def parse_description(text: str) -> dict[str, Any]:
    chapters = [
        {
            "timestamp": m.group(1),
            "label": m.group(2).strip(),
            "timestamp_seconds": timestamp_to_seconds(m.group(1)),
        }
        for m in CHAPTER_RE.finditer(text)
    ]
    raw_urls = URL_RE.findall(text)
    urls = []
    seen: set[str] = set()
    for u in raw_urls:
        if "youtube.com/redirect" in u and "q=" not in u:
            continue
        if "youtu.be/" in u or "youtube.com/watch" in u:
            continue
        canonical = normalize_url(u)
        if canonical not in seen:
            seen.add(canonical)
            urls.append(canonical)
    return {"chapters": chapters, "urls": urls}


def _chapter_url_offset(chapters: list[dict[str, Any]], urls: list[str]) -> int:
    if not chapters or not urls:
        return 0
    offset = max(0, len(chapters) - len(urls))
    if offset == 0 and len(chapters) == len(urls):
        first = chapters[0]["label"].lower()
        if "intro" in first or first.startswith("ai news"):
            offset = 1
    return min(offset, max(0, len(chapters) - 1))


def zip_chapters_to_urls(
    chapters: list[dict[str, Any]], urls: list[str]
) -> list[dict[str, Any]]:
    """Pair chapters with URLs by order (roundup channel convention).

    When the description lists more chapters than URLs (e.g. an intro segment
    without a link), align from the tail so the last N chapters map to N URLs.
    """
    items: list[dict[str, Any]] = []
    if urls:
        offset = _chapter_url_offset(chapters, urls)
        paired_chapters = chapters[offset : offset + len(urls)]
    else:
        offset = 0
        paired_chapters = []
    for i, url in enumerate(urls):
        chapter = paired_chapters[i] if i < len(paired_chapters) else None
        label = chapter["label"] if chapter else urlparse(url).netloc
        ts = chapter.get("timestamp_seconds") if chapter else None
        items.append(
            {
                "label": label,
                "url": url,
                "canonical_url": url,
                "kind": classify_url(url),
                "timestamp_seconds": ts,
            }
        )
    # Leading chapters without URLs (intro segments, etc.)
    leading = chapters[:offset]
    for chapter in leading:
        items.append(
            {
                "label": chapter["label"],
                "url": "",
                "canonical_url": f"chapter:{chapter['label'].lower().replace(' ', '-')}",
                "kind": IntelItemKind.UNKNOWN,
                "timestamp_seconds": chapter.get("timestamp_seconds"),
            }
        )
    return items


def extract_intel_items(description: str) -> list[dict[str, Any]]:
    parsed = parse_description(description)
    return zip_chapters_to_urls(parsed["chapters"], parsed["urls"])
