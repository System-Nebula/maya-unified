"""Tests for music reaction API validation."""

from __future__ import annotations

import pytest

from services.music.reactions import VALID_ENTITY_TYPES, VALID_REACTIONS


def test_valid_reaction_constants():
    assert "like" in VALID_REACTIONS
    assert "star" in VALID_REACTIONS
    assert "heart" in VALID_REACTIONS
    assert "work" in VALID_ENTITY_TYPES
    assert "set_entry" in VALID_ENTITY_TYPES


@pytest.mark.asyncio
async def test_set_reaction_rejects_invalid_type():
    from services.music.reactions import set_reaction
    import uuid

    with pytest.raises(ValueError, match="entity_type"):
        await set_reaction(
            operator_id=uuid.uuid4(),
            entity_type="invalid",
            entity_key="fp:test",
            reaction="like",
        )
