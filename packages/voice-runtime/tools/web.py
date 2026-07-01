"""Web lookup tools: search and weather (no API keys required for basics)."""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request

from config import CONFIG
from .registry import ToolSpec


def _http_get(url: str, timeout: float = 12.0) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "qwen3-voice-agent/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web via DuckDuckGo; returns titles, URLs, and snippets."""
    query = (query or "").strip()
    if not query:
        raise ValueError("query is required")
    max_results = max(1, min(int(max_results or 5), 8))
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise RuntimeError("Install ddgs: pip install ddgs") from exc

    hits: list[dict] = []
    with DDGS() as ddgs:
        for row in ddgs.text(query, max_results=max_results):
            if not isinstance(row, dict):
                continue
            hits.append({
                "title": row.get("title") or "",
                "url": row.get("href") or row.get("url") or "",
                "snippet": row.get("body") or row.get("snippet") or "",
            })
    if not hits:
        return {"query": query, "results": [], "summary": "No results found."}
    lines = []
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {h['title']}\n   {h['snippet']}\n   {h['url']}")
    return {
        "query": query,
        "results": hits,
        "summary": "\n".join(lines),
    }


def web_fetch(url: str, max_chars: int = 2400) -> dict:
    """Fetch a page and return plain text for the agent to summarize."""
    url = (url or "").strip()
    if not url:
        raise ValueError("url is required")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    html = _http_get(url, timeout=CONFIG.web.fetch_timeout)
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return {"url": url, "excerpt": text, "chars": len(text)}


def weather(location: str) -> dict:
    """Current weather via wttr.in (no API key)."""
    location = (location or "").strip()
    if not location:
        raise ValueError("location is required")
    loc = urllib.parse.quote(location)
    try:
        one_line = _http_get(
            f"https://wttr.in/{loc}?format=3",
            timeout=CONFIG.web.fetch_timeout,
        ).strip()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Weather lookup failed: {exc}") from exc
    detail = ""
    try:
        detail = _http_get(
            f"https://wttr.in/{loc}?format=%c+%C+%t+%h+%w",
            timeout=CONFIG.web.fetch_timeout,
        ).strip()
    except urllib.error.URLError:
        pass
    return {
        "location": location,
        "now": one_line,
        "detail": detail or one_line,
        "spoken": one_line.replace(":", " —", 1) if ":" in one_line else one_line,
    }


def build_web_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="web_search",
            description=(
                "Search the internet for current facts, news, or how-tos. "
                "Returns snippets and links — summarize briefly for speech."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results (1-8, default 5).",
                    },
                },
                "required": ["query"],
            },
            handler=lambda a: web_search(a.get("query", ""), a.get("max_results", 5)),
            group="web",
        ),
        ToolSpec(
            name="web_fetch",
            description=(
                "Fetch a web page URL and return plain text excerpt. "
                "Use after web_search when you need more detail from one link."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full http(s) URL."},
                },
                "required": ["url"],
            },
            handler=lambda a: web_fetch(a.get("url", "")),
            group="web",
        ),
        ToolSpec(
            name="weather",
            description=(
                "Get current weather for a city or place (e.g. 'Seattle', 'London UK'). "
                "Use when the user asks about weather, temperature, or if they need a jacket."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City, region, or place name.",
                    },
                },
                "required": ["location"],
            },
            handler=lambda a: weather(a.get("location", "")),
            group="web",
        ),
    ]
