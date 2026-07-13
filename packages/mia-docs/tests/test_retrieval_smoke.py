import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="requires postgres (DATABASE_URL)"
)


def test_ingest_query_expand(tmp_path, sample_pages):
    """End to end: fixture recipes -> notes/edges -> query -> expansion."""
    from maya_db.models import AtomicNote
    from mia_docs import embeddings, ids
    from mia_docs.extraction import canonical
    from mia_docs.extraction.recipe import split_recipes
    from mia_docs.predicates import Predicate
    from mia_docs.retrieval import search
    from mia_docs.store import get_session, upsert_edge, upsert_note

    source_hash = "smoketest" + "0" * 55
    session = get_session()
    blocks = split_recipes(sample_pages)
    note_ids = []
    try:
        for block in blocks:
            rid = ids.note_id(block.raw_text, source_hash, (block.page_start, block.page_end))
            note_ids.append(rid)
            vec = embeddings.embed(
                [embeddings.recipe_embed_text(
                    block.title, [i.name or i.raw_string for i in block.ingredients], block.steps
                )]
            )[0]
            upsert_note(
                session, id=rid, title=block.title, content=block.raw_text,
                note_type="smoke_recipe", embedding=vec,
                meta={"servings": block.servings},
            )
            for ing in block.ingredients[:2]:
                name = canonical.normalize_ingredient(ing.name or ing.raw_string)
                iid = ids.entity_id("ingredient", name)
                note_ids.append(iid)
                upsert_note(session, id=iid, title=name, content=name, note_type="ingredient")
                upsert_edge(session, rid, iid, Predicate.CONTAINS,
                            meta={"quantity": ing.quantity, "unit": ing.unit})
        session.commit()

        hits = search(
            "rice with saffron", note_type="smoke_recipe",
            rerank=True, expand_links=1, session=session,
        )
        assert hits
        assert hits[0].note.title == "Saffron Rice Pilaf"
        assert Predicate.CONTAINS.value in hits[0].linked

        filtered = search(
            "chicken", note_type="smoke_recipe",
            filters=["metadata.servings<=2"], session=session,
        )
        assert [h.note.title for h in filtered] == ["Lemon Garlic Chicken"]
    finally:
        session.rollback()
        session.query(AtomicNote).filter(AtomicNote.id.in_(note_ids)).delete(
            synchronize_session=False
        )
        session.commit()
        session.close()
