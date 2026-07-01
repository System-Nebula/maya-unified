"""Tests for ontology projector pure functions."""

from __future__ import annotations

from maya_graph.projector import jaccard_edges, normalize_key


def test_normalize_key() -> None:
    assert normalize_key("Drum & Bass") == "drum-and-bass"
    assert normalize_key("  Ivy Lab  ") == "ivy-lab"


def test_jaccard_edges_threshold() -> None:
    membership = {
        "a": {"g1", "g2", "g3"},
        "b": {"g2", "g3", "g4"},
        "c": {"g9"},
    }
    pairs = list(jaccard_edges(membership, threshold=0.3, min_shared=2))
    assert len(pairs) == 1
    left, right, weight, shared = pairs[0]
    assert {left, right} == {"a", "b"}
    assert weight == 0.5
    assert shared == ["g2", "g3"]
