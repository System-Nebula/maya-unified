"""Fetch and extract web pages as markdown."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from maya_contracts import FetchedPage, WebSearchResult
from maya_research.config import load_config
from maya_research.storage.artifacts import store_markdown, url_hash
from maya_research.tools.credibility import score_domain


class PageFetcher:
    def __init__(self) -> None:
        self._cfg = load_config()
        self._domain_last_fetch: dict[str, float] = defaultdict(float)
        self._robots_cache: dict[str, RobotFileParser] = {}

    async def fetch_urls(
        self,
        urls: list[str],
        *,
        operator_urls: set[str] | None = None,
        min_credibility: float | None = None,
    ) -> list[FetchedPage]:
        min_cred = min_credibility or self._cfg.page_fetch_min_credibility
        operator_urls = operator_urls or set()
        pages: list[FetchedPage] = []
        for url in urls[: self._cfg.max_pages_per_run]:
            cred = score_domain(url)
            if url not in operator_urls and cred < min_cred:
                continue
            if operator_urls and url in operator_urls:
                cred = min(1.0, cred + self._cfg.operator_history_boost)
            page = await self.fetch_one(url, operator_visited=url in operator_urls, credibility=cred)
            if page:
                pages.append(page)
        return pages

    async def fetch_from_search_results(
        self,
        results: list[WebSearchResult],
        *,
        operator_urls: set[str] | None = None,
    ) -> list[FetchedPage]:
        urls = [r.url for r in sorted(results, key=lambda x: x.credibility_score, reverse=True)]
        return await self.fetch_urls(urls, operator_urls=operator_urls)

    async def fetch_one(
        self,
        url: str,
        *,
        operator_visited: bool = False,
        credibility: float | None = None,
    ) -> FetchedPage | None:
        domain = urlparse(url).netloc
        if not await self._allowed(url, domain):
            return None
        await self._rate_limit(domain)
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "maya-research/0.1"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    return None
                html = resp.text
        except httpx.HTTPError:
            return None

        title, markdown = _extract_markdown(html, url)
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        artifact_id, artifact_key = await store_markdown(
            f"# {title}\n\nSource: {url}\n\n{markdown}",
            suffix="md",
        )
        return FetchedPage(
            url=url,
            title=title,
            markdown=markdown[:50000],
            content_hash=content_hash,
            artifact_key=artifact_key or artifact_id,
            credibility_score=credibility or score_domain(url),
            operator_visited=operator_visited,
            fetched_at=datetime.now(timezone.utc),
        )

    async def _rate_limit(self, domain: str, min_interval: float = 1.0) -> None:
        now = time.monotonic()
        elapsed = now - self._domain_last_fetch[domain]
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._domain_last_fetch[domain] = time.monotonic()

    async def _allowed(self, url: str, domain: str) -> bool:
        if not domain:
            return False
        rp = self._robots_cache.get(domain)
        if rp is None:
            rp = RobotFileParser()
            rp.set_url(f"https://{domain}/robots.txt")
            try:
                rp.read()
            except Exception:
                pass
            self._robots_cache[domain] = rp
        try:
            return rp.can_fetch("maya-research", url)
        except Exception:
            return True


def _extract_markdown(html: str, url: str) -> tuple[str, str]:
    try:
        import trafilatura

        extracted = trafilatura.extract(html, url=url, include_comments=False)
        if extracted:
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
            title = title_match.group(1).strip() if title_match else url
            return title, extracted
    except ImportError:
        pass
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = title_match.group(1).strip() if title_match else url
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return title, text[:20000]
