"""Deterministic ingest orchestrator (sk mine). Zero LLM on the write path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from mia_docs import embeddings, ids
from mia_docs.extraction import canonical, pdf, recipe
from mia_docs.predicates import Predicate
from mia_docs.store import get_session, upsert_edge, upsert_note

RELATED_THRESHOLD = 0.82
INGEST_VERSION = 1


@dataclass
class IngestReport:
    source: str
    recipes: int = 0
    low_confidence: int = 0
    ingredients: int = 0
    techniques: int = 0
    related_edges: int = 0
    text_coverage: float = 1.0


def ingest_pdf(
    pdf_path: str | Path,
    note_type: str = "recipe",
    session: Session | None = None,
) -> IngestReport:
    pdf_path = Path(pdf_path)
    report = IngestReport(source=str(pdf_path))
    report.text_coverage = pdf.text_coverage(pdf_path)

    source_hash = pdf.doc_hash(pdf_path)
    pages = list(pdf.extract_pages(pdf_path))
    blocks = recipe.split_recipes(pages)
    if not blocks:
        return report

    alias = canonical.build_alias_table(
        [i.name or i.raw_string for b in blocks for i in b.ingredients]
    )

    own_session = session is None
    session = session or get_session()
    now = datetime.now(timezone.utc)
    try:
        embed_texts = [
            embeddings.recipe_embed_text(
                b.title, [i.name or i.raw_string for i in b.ingredients], b.steps
            )
            for b in blocks
        ]
        vectors = embeddings.embed(embed_texts)

        recipe_ids: list[str] = []
        for block, vector in zip(blocks, vectors):
            rid = ids.note_id(
                block.raw_text, source_hash, (block.page_start, block.page_end)
            )
            recipe_ids.append(rid)
            report.recipes += 1
            if block.extraction_confidence == "low":
                report.low_confidence += 1
            upsert_note(
                session,
                id=rid,
                title=block.title,
                content=block.raw_text,
                note_type=note_type,
                labels=[f"confidence:{block.extraction_confidence}"],
                meta={
                    "source_path": str(pdf_path),
                    "source_hash": source_hash,
                    "page_range": [block.page_start, block.page_end],
                    "servings": block.servings,
                    "prep_min": block.prep_min,
                    "cook_min": block.cook_min,
                    "extraction_confidence": block.extraction_confidence,
                    "ingest_version": INGEST_VERSION,
                },
                embedding=vector,
                source_doc_hash=source_hash,
                page_start=block.page_start,
                page_end=block.page_end,
                valid_start=now,
            )

            seen_ingredients: set[str] = set()
            for ing in block.ingredients:
                name = canonical.normalize_ingredient(ing.name or ing.raw_string)
                name = alias.get(name, name)
                if not name or name in seen_ingredients:
                    continue
                seen_ingredients.add(name)
                iid = ids.entity_id("ingredient", name)
                upsert_note(
                    session,
                    id=iid,
                    title=name,
                    content=name,
                    note_type="ingredient",
                )
                upsert_edge(
                    session,
                    rid,
                    iid,
                    Predicate.CONTAINS,
                    meta={
                        "quantity": ing.quantity,
                        "unit": ing.unit,
                        "raw_string": ing.raw_string,
                    },
                )
                report.ingredients += 1

            for tech in canonical.match_techniques(block.steps):
                tid = ids.entity_id("technique", tech)
                upsert_note(
                    session, id=tid, title=tech, content=tech, note_type="technique"
                )
                upsert_edge(session, rid, tid, Predicate.EMPLOYS)
                report.techniques += 1

        # RELATED_TO: recipe-recipe similarity within this ingest batch
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                sim = embeddings.cosine(vectors[i], vectors[j])
                if sim >= RELATED_THRESHOLD:
                    upsert_edge(
                        session,
                        recipe_ids[i],
                        recipe_ids[j],
                        Predicate.RELATED_TO,
                        weight=sim,
                    )
                    upsert_edge(
                        session,
                        recipe_ids[j],
                        recipe_ids[i],
                        Predicate.RELATED_TO,
                        weight=sim,
                    )
                    report.related_edges += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()
    return report
