#!/usr/bin/env python3
"""Smoke evaluation for text embedders against a local sample."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from numpy.linalg import norm

# Reuse the existing embed_worker if available; otherwise this is a standalone prototype.

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (norm(a) * norm(b)))


def mean_reciprocal_rank(queries: list[str], corpus: list[str], embed_fn) -> float:
    """MRR over a synthetic retrieval task: each query is matched to itself in corpus."""
    all_texts = list(dict.fromkeys(corpus + queries))
    embeddings = [embed_fn(t) for t in all_texts]
    text_to_vec = dict(zip(all_texts, embeddings))

    rr_sum = 0.0
    for q in queries:
        q_vec = text_to_vec[q]
        scores = [
            (text, cosine_similarity(q_vec, text_to_vec[text]))
            for text in all_texts
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        for rank, (text, _) in enumerate(scores, start=1):
            if text == q:
                rr_sum += 1.0 / rank
                break
    return rr_sum / len(queries)


def mock_embed(text: str, dim: int = 768, seed: int = 42) -> np.ndarray:
    """Deterministic mock embedder for prototyping without GPU."""
    rng = np.random.default_rng(hash(text) % (2**31) + seed)
    vec = rng.random(dim).astype(np.float32)
    return vec / norm(vec)


def mock_embedder_a(text: str) -> np.ndarray:
    return mock_embed(text, dim=768, seed=42)


def mock_embedder_b(text: str) -> np.ndarray:
    return mock_embed(text, dim=768, seed=99)


def run_eval(
    model_a_name: str,
    embed_a,
    model_b_name: str,
    embed_b,
    corpus_path: Path | None,
) -> dict[str, Any]:
    queries = [
        "brooke monk outfit",
        "olivia rodrigo performance",
        "jordyn jones dance",
        "andrea botez chess",
        "shay cosplay",
    ]

    if corpus_path and corpus_path.exists():
        corpus = corpus_path.read_text().splitlines()
        corpus = [line.strip() for line in corpus if line.strip()]
    else:
        corpus = queries + [
            "lexie tall brunette",
            "liv party dress",
            "random unrelated text",
        ]

    mrr_a = mean_reciprocal_rank(queries, corpus, embed_a)
    mrr_b = mean_reciprocal_rank(queries, corpus, embed_b)

    return {
        "model_a": model_a_name,
        "model_b": model_b_name,
        "corpus_size": len(corpus),
        "queries": len(queries),
        "mrr": {model_a_name: round(mrr_a, 4), model_b_name: round(mrr_b, 4)},
        "winner": model_a_name if mrr_a > mrr_b else model_b_name,
        "delta": round(abs(mrr_a - mrr_b), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke eval for embedders")
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-run", action="store_true", help="Write EvalRun to DB")
    parser.add_argument("--model-a", default="nomic-embed-text-v1.5")
    parser.add_argument("--model-b", default="jina-embeddings-v3")
    args = parser.parse_args()

    results = run_eval(
        args.model_a,
        mock_embedder_a,
        args.model_b,
        mock_embedder_b,
        args.corpus,
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"Corpus: {results['corpus_size']} docs, {results['queries']} queries")
        print(f"  {results['model_a']} MRR: {results['mrr'][results['model_a']]}")
        print(f"  {results['model_b']} MRR: {results['mrr'][results['model_b']]}")
        print(f"Winner: {results['winner']} (+{results['delta']})")

    if args.write_run:
        try:
            import asyncio
            from datetime import datetime, timezone
            from maya_db import EvalRun as EvalRunDB, get_async_session
            from maya_contracts import EvalType

            async def persist() -> None:
                async for session in get_async_session():
                    run = EvalRunDB(
                        model_release_id="mock-release-id",
                        eval_suite="house_retrieval_smoke",
                        eval_type=EvalType.DATASET_SCORED.value,
                        status="completed",
                        metrics=results,
                        started_at=datetime.now(timezone.utc),
                        completed_at=datetime.now(timezone.utc),
                    )
                    session.add(run)
                    await session.commit()
                    print(f"EvalRun persisted: {run.id}")

            asyncio.run(persist())
        except Exception as e:
            print(f"DB write failed: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
