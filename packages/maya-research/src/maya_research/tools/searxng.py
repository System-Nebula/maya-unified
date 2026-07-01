"""SearXNG search client."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from maya_contracts import WebSearchResult
from maya_research.tools.credibility import extract_domain, score_domain


class SearxngClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def search(self, query: str, *, limit: int = 10) -> list[WebSearchResult]:
        params = {"q": query, "format": "json", "language": "en"}
        url = f"{self._base_url}?{urlencode(params)}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()

        now = datetime.now(timezone.utc)
        results: list[WebSearchResult] = []
        for item in data.get("results", [])[:limit]:
            link = item.get("url") or item.get("link") or ""
            if not link:
                continue
            domain = extract_domain(link)
            results.append(
                WebSearchResult(
                    url=link,
                    title=item.get("title") or link,
                    snippet=item.get("content") or item.get("snippet") or "",
                    domain=domain,
                    credibility_score=score_domain(link),
                    fetched_at=now,
                )
            )
        return results

    async def two_pass_search(
        self, query: str, *, broad_limit: int = 10, focused_limit: int = 8
    ) -> list[WebSearchResult]:
        broad = await self.search(query, limit=broad_limit)
        terms = _extract_terms(broad)
        if not terms:
            return broad
        focused_query = f"{query} {' '.join(terms[:5])}"
        focused = await self.search(focused_query, limit=focused_limit)
        return _dedupe_results(broad + focused)


def _extract_terms(results: list[WebSearchResult]) -> list[str]:
    words: dict[str, int] = {}
    stop = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "has"}
    for r in results:
        for token in (r.title + " " + r.snippet).lower().split():
            token = "".join(c for c in token if c.isalnum())
            if len(token) < 4 or token in stop:
                continue
            words[token] = words.get(token, 0) + 1
    ranked = sorted(words.items(), key=lambda kv: kv[1], reverse=True)
    return [w for w, _ in ranked[:8]]


def _dedupe_results(results: list[WebSearchResult]) -> list[WebSearchResult]:
    seen: set[str] = set()
    out: list[WebSearchResult] = []
    for r in results:
        if r.url in seen:
            continue
        seen.add(r.url)
        out.append(r)
    return out
