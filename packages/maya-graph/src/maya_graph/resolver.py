"""PersonResolver: aggregate pairwise signals into a confidence score."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from maya_contracts import MatchSignal, MatchSignalKind

from maya_graph.signals import (
    bio_text_signal,
    embedding_proximity_signal,
    face_match_signal,
    handle_similarity_signal,
    profile_link_signal,
)


@dataclass(frozen=True)
class ResolverInput:
    channel_id: str
    platform: str
    handle: str
    display_name: str
    bio: Optional[str] = None
    bio_embedding: Optional[Sequence[float]] = None
    avatar_embedding: Optional[Sequence[float]] = None
    profile_links: Sequence[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ResolverConfig:
    weights: dict[MatchSignalKind, float] = field(
        default_factory=lambda: {
            MatchSignalKind.HANDLE_SIMILARITY: 0.30,
            MatchSignalKind.BIO_TEXT_MATCH: 0.25,
            MatchSignalKind.PROFILE_LINK_MATCH: 0.25,
            MatchSignalKind.AVATAR_FACE_MATCH: 0.15,
            MatchSignalKind.EMBEDDING_PROXIMITY: 0.05,
        }
    )
    auto_link_threshold: float = 0.85
    suggest_threshold: float = 0.55


class PersonResolver:
    def __init__(self, config: Optional[ResolverConfig] = None) -> None:
        self.config = config or ResolverConfig()

    def score(
        self, a: ResolverInput, b: ResolverInput
    ) -> tuple[float, list[MatchSignal]]:
        signals: list[MatchSignal] = [handle_similarity_signal(a.handle, b.handle)]

        if (sig := bio_text_signal(a.bio_embedding, b.bio_embedding)) is not None:
            signals.append(sig)
        if (sig := profile_link_signal(a.profile_links, b.handle, b.platform)) is not None:
            signals.append(sig)
        elif (sig := profile_link_signal(b.profile_links, a.handle, a.platform)) is not None:
            signals.append(sig)
        if (sig := face_match_signal(a.avatar_embedding, b.avatar_embedding)) is not None:
            signals.append(sig)
        if (sig := embedding_proximity_signal(a.bio_embedding, b.bio_embedding)) is not None:
            signals.append(sig)

        total_weight = sum(self.config.weights.get(s.kind, 0) for s in signals)
        if total_weight == 0:
            return 0.0, signals
        weighted = sum(self.config.weights.get(s.kind, 0) * s.score for s in signals)
        return weighted / total_weight, signals

    def decide(self, confidence: float) -> str:
        if confidence >= self.config.auto_link_threshold:
            return "auto_link"
        if confidence >= self.config.suggest_threshold:
            return "suggest"
        return "ignore"
