import os

import pytest

from mia_docs.ids import entity_id, note_id


def test_note_id_deterministic():
    a = note_id("some recipe text", "abc123", (4, 6))
    b = note_id("some recipe text", "abc123", (4, 6))
    assert a == b
    assert len(a) == 64


def test_note_id_sensitive_to_inputs():
    base = note_id("text", "hash", (1, 2))
    assert note_id("text!", "hash", (1, 2)) != base
    assert note_id("text", "hash2", (1, 2)) != base
    assert note_id("text", "hash", (1, 3)) != base


def test_entity_id_namespaced():
    assert entity_id("ingredient", "saffron") != entity_id("technique", "saffron")


@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="requires postgres (DATABASE_URL)"
)
def test_upsert_version_bump_no_duplicate():
    from sqlalchemy import func, select

    from maya_db.models import AtomicNote
    from mia_docs.store import get_session, upsert_note

    nid = note_id("dedup-test-recipe", "testhash", (1, 1))
    session = get_session()
    try:
        session.query(AtomicNote).filter_by(id=nid).delete()
        session.commit()

        upsert_note(
            session, id=nid, title="Dedup Test", content="body", note_type="recipe"
        )
        session.commit()
        upsert_note(
            session, id=nid, title="Dedup Test", content="body", note_type="recipe"
        )
        session.commit()

        count = session.execute(
            select(func.count()).select_from(AtomicNote).where(AtomicNote.id == nid)
        ).scalar_one()
        note = session.get(AtomicNote, nid)
        assert count == 1
        assert note.version == 2
    finally:
        session.query(AtomicNote).filter_by(id=nid).delete()
        session.commit()
        session.close()
