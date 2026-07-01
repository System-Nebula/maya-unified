"""Domain credibility scoring heuristics."""

from __future__ import annotations

from urllib.parse import urlparse

_HIGH_TRUST_SUFFIXES = (".edu", ".gov", ".ac.uk")
_HIGH_TRUST_DOMAINS = {
    "arxiv.org",
    "github.com",
    "huggingface.co",
    "research.google",
    "research.nvidia.com",
    "openai.com",
    "anthropic.com",
    "nature.com",
    "ieee.org",
    "acm.org",
}
_LOW_TRUST_HINTS = ("blogspot.", "medium.com", "substack.com")


def extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.netloc or "").lower().removeprefix("www.")


def score_domain(url: str) -> float:
    domain = extract_domain(url)
    if not domain:
        return 0.3
    if any(domain.endswith(s) for s in _HIGH_TRUST_SUFFIXES):
        return 0.9
    if domain in _HIGH_TRUST_DOMAINS or any(domain.endswith(f".{d}") for d in _HIGH_TRUST_DOMAINS):
        return 0.85
    if any(h in domain for h in _LOW_TRUST_HINTS):
        return 0.45
    if domain.endswith(".io") or domain.endswith(".ai"):
        return 0.6
    return 0.5
