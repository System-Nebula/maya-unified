"""GitHub REST API client for release compare diffs."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

_GITHUB_API = "https://api.github.com"
_DEFAULT_IGNORE = [
    r"^tests?/",
    r"\.lock$",
    r"^\.github/",
    r"^Cargo\.lock$",
    r"CHANGELOG",
]


@dataclass(frozen=True)
class CompareFile:
    filename: str
    status: str
    additions: int
    deletions: int
    patch: Optional[str]


@dataclass(frozen=True)
class CompareResult:
    repo: str
    from_tag: Optional[str]
    to_tag: str
    files: list[CompareFile]
    total_commits: int


def parse_repo_slug(handle: str) -> tuple[str, str]:
    """Normalize owner/repo from handle or GitHub URL."""
    handle = handle.strip().rstrip("/")
    if handle.startswith("https://github.com/"):
        handle = handle.removeprefix("https://github.com/")
    if handle.endswith("/releases.atom"):
        handle = handle.removesuffix("/releases.atom")
    if handle.endswith("/releases"):
        handle = handle.removesuffix("/releases")
    parts = handle.split("/")
    if len(parts) < 2:
        raise ValueError(f"invalid github repo handle: {handle!r}")
    return parts[0], parts[1]


def extract_tag_from_release_url(url: str) -> str:
    """Extract tag name from a GitHub release URL or Atom entry link."""
    if "/releases/tag/" in url:
        return url.rsplit("/releases/tag/", 1)[-1].split("?")[0]
    if "/releases/" in url:
        tail = url.rsplit("/releases/", 1)[-1].split("?")[0]
        if tail and tail != "latest":
            return tail
    return url.rsplit("/", 1)[-1]


class GitHubApiClient:
    def __init__(
        self,
        token: Optional[str] = None,
        http: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._token = token or os.getenv("GITHUB_TOKEN")
        self._http = http
        self._owns_http = http is None

    async def __aenter__(self) -> GitHubApiClient:
        if self._http is None:
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": "maya-feeds/1.0",
            }
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._http = httpx.AsyncClient(timeout=30.0, headers=headers)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        assert self._http is not None
        resp = await self._http.get(f"{_GITHUB_API}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def list_releases(self, owner: str, repo: str, limit: int = 30) -> list[dict]:
        data = await self._get(
            f"/repos/{owner}/{repo}/releases",
            params={"per_page": limit},
        )
        return data if isinstance(data, list) else []

    async def resolve_prev_tag(
        self, owner: str, repo: str, new_tag: str
    ) -> Optional[str]:
        releases = await self.list_releases(owner, repo)
        tags = [r.get("tag_name") for r in releases if r.get("tag_name")]
        if new_tag in tags:
            idx = tags.index(new_tag)
            if idx + 1 < len(tags):
                return tags[idx + 1]
        for tag in tags:
            if tag != new_tag:
                return tag
        return None

    async def compare_tags(
        self, owner: str, repo: str, base: str, head: str
    ) -> CompareResult:
        slug = f"{owner}/{repo}"
        data = await self._get(f"/repos/{owner}/{repo}/compare/{base}...{head}")
        files: list[CompareFile] = []
        for f in data.get("files") or []:
            files.append(
                CompareFile(
                    filename=f.get("filename", ""),
                    status=f.get("status", "modified"),
                    additions=f.get("additions", 0),
                    deletions=f.get("deletions", 0),
                    patch=f.get("patch"),
                )
            )
        return CompareResult(
            repo=slug,
            from_tag=base,
            to_tag=head,
            files=files,
            total_commits=data.get("total_commits", 0),
        )


def relevant_files(
    files: list[CompareFile],
    ignore_patterns: Optional[list[str]] = None,
    max_patch_chars: int = 8000,
) -> list[CompareFile]:
    patterns = ignore_patterns if ignore_patterns is not None else _DEFAULT_IGNORE
    compiled = [re.compile(p) for p in patterns]
    out: list[CompareFile] = []
    for f in files:
        if f.patch is None:
            continue
        if any(p.search(f.filename) for p in compiled):
            continue
        patch = f.patch
        if patch and len(patch) > max_patch_chars:
            patch = patch[:max_patch_chars] + "\n... [truncated]"
        out.append(
            CompareFile(
                filename=f.filename,
                status=f.status,
                additions=f.additions,
                deletions=f.deletions,
                patch=patch,
            )
        )
    return out


def chunk_patches(
    files: list[CompareFile], max_chars: int = 24000
) -> list[list[CompareFile]]:
    """Group files into chunks that fit within a token budget proxy."""
    chunks: list[list[CompareFile]] = []
    current: list[CompareFile] = []
    current_size = 0
    for f in files:
        size = len(f.patch or "") + len(f.filename) + 32
        if current and current_size + size > max_chars:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(f)
        current_size += size
    if current:
        chunks.append(current)
    return chunks if chunks else [[]]
