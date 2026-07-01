"""Pairwise match signals used by PersonResolver."""

from __future__ import annotations

import math
import re
from typing import Optional, Sequence

from maya_contracts import MatchSignal, MatchSignalKind
from rapidfuzz.distance import JaroWinkler


_HANDLE_NOISE = re.compile(r"[^a-z0-9]")


def _normalize_handle(handle: str) -> str:
    return _HANDLE_NOISE.sub("", handle.lower().lstrip("@"))


def handle_similarity_signal(handle_a: str, handle_b: str) -> MatchSignal:
    score = JaroWinkler.normalized_similarity(
        _normalize_handle(handle_a), _normalize_handle(handle_b)
    )
    return MatchSignal(
        kind=MatchSignalKind.HANDLE_SIMILARITY,
        score=float(score),
        detail=f"{handle_a} ~ {handle_b}",
    )


def bio_text_signal(
    embedding_a: Optional[Sequence[float]],
    embedding_b: Optional[Sequence[float]],
) -> Optional[MatchSignal]:
    if not embedding_a or not embedding_b:
        return None
    score = _cosine(embedding_a, embedding_b)
    return MatchSignal(kind=MatchSignalKind.BIO_TEXT_MATCH, score=score)


def profile_link_signal(
    links_a: Sequence[dict], handle_b: str, platform_b: str
) -> Optional[MatchSignal]:
    needle = _normalize_handle(handle_b)
    if not needle:
        return None
    platform_token = platform_b.lower()
    for link in links_a:
        url = (link.get("url") or "").lower()
        if not url:
            continue
        if platform_token in url and needle in _HANDLE_NOISE.sub("", url):
            return MatchSignal(
                kind=MatchSignalKind.PROFILE_LINK_MATCH,
                score=1.0,
                detail=url,
            )
    return None


def face_match_signal(
    embedding_a: Optional[Sequence[float]],
    embedding_b: Optional[Sequence[float]],
) -> Optional[MatchSignal]:
    if not embedding_a or not embedding_b:
        return None
    return MatchSignal(
        kind=MatchSignalKind.AVATAR_FACE_MATCH,
        score=_cosine(embedding_a, embedding_b),
    )


def embedding_proximity_signal(
    embedding_a: Optional[Sequence[float]],
    embedding_b: Optional[Sequence[float]],
) -> Optional[MatchSignal]:
    if not embedding_a or not embedding_b:
        return None
    return MatchSignal(
        kind=MatchSignalKind.EMBEDDING_PROXIMITY,
        score=_cosine(embedding_a, embedding_b),
    )


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("embedding length mismatch")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))
