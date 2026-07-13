"""Hybrid retrieval (sk query): SQL prune → vector recall → rerank → expand."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from maya_db.models import AtomicNote
from mia_docs import embeddings
from mia_docs.predicates import Predicate
from mia_docs.store import get_session, neighbors, vector_candidates

CANDIDATE_LIMIT = 40
MAX_EXPAND_HOPS = 2
EXPAND_CAP_PER_NOTE = 5

_FILTER_RE = re.compile(r"^(?:metadata\.)?(\w+)\s*(<=|>=|<|>|=)\s*(.+)$")


@dataclass
class SearchHit:
    note: AtomicNote
    score: float
    linked: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def parse_filter(expr: str) -> tuple[str, tuple[str, Any]]:
    """'metadata.servings<=4' -> ('servings', ('<=', 4))"""
    m = _FILTER_RE.match(expr.strip())
    if not m:
        raise ValueError(f"bad filter expression: {expr!r}")
    key, op, val = m.group(1), m.group(2), m.group(3).strip()
    try:
        val = int(val)
    except ValueError:
        try:
            val = float(val)
        except ValueError:
            pass
    return key, (op, val)


def _bm25_scores(query: str, docs: list[str]) -> list[float]:
    # BM25Plus: Okapi's IDF collapses to 0 on small candidate sets
    from rank_bm25 import BM25Plus

    tokenized = [d.lower().split() for d in docs]
    bm25 = BM25Plus(tokenized)
    return list(bm25.get_scores(query.lower().split()))


def _cross_encoder_scores(query: str, docs: list[str]) -> list[float] | None:
    try:
        from sentence_transformers import CrossEncoder

        model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return [float(s) for s in model.predict([(query, d) for d in docs])]
    except Exception:
        return None


def _rrf(rankings: list[list[int]], k: int = 60) -> list[float]:
    n = len(rankings[0]) if rankings else 0
    fused = [0.0] * n
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] += 1.0 / (k + rank + 1)
    return fused


def search(
    query: str,
    note_type: str | None = "recipe",
    labels: list[str] | None = None,
    filters: list[str] | None = None,
    rerank: bool = False,
    expand_links: int = 0,
    top_k: int = 10,
    session=None,
) -> list[SearchHit]:
    own_session = session is None
    session = session or get_session()
    try:
        meta_filters = dict(parse_filter(f) for f in (filters or []))
        qv = embeddings.embed([query])[0]
        candidates = vector_candidates(
            session,
            qv,
            note_type=note_type,
            labels=labels,
            meta_filters=meta_filters or None,
            limit=CANDIDATE_LIMIT,
        )
        if not candidates:
            return []

        notes = [n for n, _ in candidates]
        scores = [s for _, s in candidates]

        if rerank and len(notes) > 1:
            docs = [f"{n.title}\n{n.content[:2000]}" for n in notes]
            # BM25 weighted into the fusion — ingredient names are
            # exact-match-sensitive in a way generic prose isn't.
            vec_rank = sorted(range(len(notes)), key=lambda i: -scores[i])
            bm25 = _bm25_scores(query, docs)
            bm25_rank = sorted(range(len(notes)), key=lambda i: -bm25[i])
            rankings = [vec_rank, bm25_rank, bm25_rank]
            ce = _cross_encoder_scores(query, docs)
            if ce is not None:
                rankings.append(sorted(range(len(notes)), key=lambda i: -ce[i]))
            fused = _rrf(rankings)
            order = sorted(range(len(notes)), key=lambda i: -fused[i])
            notes = [notes[i] for i in order]
            scores = [fused[i] for i in order]

        hits = [SearchHit(note=n, score=s) for n, s in zip(notes, scores)][:top_k]

        if expand_links > 0:
            _expand(session, hits, min(expand_links, MAX_EXPAND_HOPS))
        return hits
    finally:
        if own_session:
            session.close()


def _expand(session, hits: list[SearchHit], hops: int) -> None:
    frontier = {h.note.id: h for h in hits}
    seen = set(frontier)
    for _ in range(hops):
        edges = neighbors(
            session,
            list(frontier),
            predicates=[Predicate.CONTAINS, Predicate.EMPLOYS, Predicate.RELATED_TO],
            cap_per_note=EXPAND_CAP_PER_NOTE,
        )
        next_frontier: dict[str, SearchHit] = {}
        for src_id, pairs in edges.items():
            hit = frontier.get(src_id)
            for edge, note in pairs:
                if hit is not None:
                    hit.linked.setdefault(edge.predicate, []).append(
                        {
                            "id": note.id,
                            "title": note.title,
                            "note_type": note.note_type,
                            "meta": edge.meta,
                            "weight": edge.weight,
                        }
                    )
                if note.id not in seen:
                    seen.add(note.id)
                    # deeper hops only expand, attaching to the origin hit
                    if hit is not None:
                        next_frontier[note.id] = hit
        frontier = next_frontier
        if not frontier:
            break
