"""Reddit public JSON API client."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from maya_contracts import RedditPost, SentimentBundle


class RedditClient:
    def __init__(self, user_agent: str, *, timeout: float = 30.0) -> None:
        self._user_agent = user_agent
        self._timeout = timeout

    async def search_subreddit(
        self,
        subreddit: str,
        query: str,
        *,
        limit: int = 25,
        sort: str = "new",
    ) -> list[RedditPost]:
        sub = subreddit.removeprefix("r/").removeprefix("/r/")
        url = (
            f"https://www.reddit.com/r/{quote(sub)}/search.json"
            f"?q={quote(query)}&sort={sort}&limit={limit}&restrict_sr=1"
        )
        headers = {"User-Agent": self._user_agent}
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 429:
                await asyncio.sleep(2.0)
                resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        posts: list[RedditPost] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            post_id = d.get("id") or ""
            permalink = d.get("permalink") or ""
            post_url = f"https://www.reddit.com{permalink}" if permalink else d.get("url", "")
            comments = await self._fetch_top_comments(client=None, permalink=permalink)
            posts.append(
                RedditPost(
                    id=post_id,
                    title=d.get("title") or "",
                    url=post_url,
                    score=int(d.get("score") or 0),
                    num_comments=int(d.get("num_comments") or 0),
                    selftext=(d.get("selftext") or "")[:2000],
                    top_comments=comments,
                )
            )
        return posts

    async def _fetch_top_comments(
        self, *, client: httpx.AsyncClient | None, permalink: str, limit: int = 5
    ) -> list[str]:
        if not permalink:
            return []
        url = f"https://www.reddit.com{permalink}.json?limit={limit}&depth=1"
        headers = {"User-Agent": self._user_agent}
        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout, headers=headers)
            close_client = True
        try:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return []
            payload = resp.json()
            if not isinstance(payload, list) or len(payload) < 2:
                return []
            comments_block = payload[1].get("data", {}).get("children", [])
            out: list[str] = []
            for c in comments_block[:limit]:
                body = c.get("data", {}).get("body")
                if body:
                    out.append(body[:500])
            return out
        finally:
            if close_client:
                await client.aclose()

    async def build_sentiment_bundle(
        self,
        subreddit: str,
        query: str,
        *,
        limit: int = 15,
    ) -> SentimentBundle:
        posts = await self.search_subreddit(subreddit, query, limit=limit)
        themes = _extract_themes(posts)
        quotes = _extract_quotes(posts)
        summary = _heuristic_sentiment_summary(posts, themes)
        return SentimentBundle(
            subreddit=subreddit,
            query=query,
            posts=posts,
            sentiment_summary=summary,
            recurring_themes=themes,
            notable_quotes=quotes,
            fetched_at=datetime.now(timezone.utc),
        )


def _extract_themes(posts: list[RedditPost]) -> list[str]:
    words: dict[str, int] = {}
    for p in posts:
        for token in (p.title + " " + p.selftext).lower().split():
            token = "".join(c for c in token if c.isalnum())
            if len(token) < 5:
                continue
            words[token] = words.get(token, 0) + 1
    ranked = sorted(words.items(), key=lambda kv: kv[1], reverse=True)
    return [w for w, c in ranked[:6] if c > 1]


def _extract_quotes(posts: list[RedditPost]) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for p in sorted(posts, key=lambda x: x.score, reverse=True):
        for c in p.top_comments:
            key = c[:80]
            if key in seen:
                continue
            seen.add(key)
            quotes.append(f"[{p.title[:60]}] {c[:240]}")
            if len(quotes) >= 5:
                return quotes
    return quotes


def _heuristic_sentiment_summary(posts: list[RedditPost], themes: list[str]) -> str:
    if not posts:
        return "No recent Reddit posts found for this query."
    avg_score = sum(p.score for p in posts) / len(posts)
    tone = "mixed"
    if avg_score > 50:
        tone = "generally positive"
    elif avg_score < 10:
        tone = "muted or skeptical"
    theme_str = ", ".join(themes[:4]) if themes else "no strong recurring themes"
    return (
        f"Analyzed {len(posts)} posts with {tone} engagement. "
        f"Recurring themes: {theme_str}."
    )
