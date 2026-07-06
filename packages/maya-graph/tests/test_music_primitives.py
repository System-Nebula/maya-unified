"""Tests for the normalized music primitives."""

from __future__ import annotations

from maya_graph.music.primitives import (
    SourceRef,
    canonical_fingerprint,
    work_key_from_fingerprint,
)


def test_canonical_fingerprint_normalizes_case_and_punct() -> None:
    a = canonical_fingerprint("Ivy Lab", "Infinite Falling Ground")
    b = canonical_fingerprint("  ivy lab ", "Infinite   Falling Ground!")
    assert a == b
    assert a == "ivy-lab::infinite-falling-ground::::original"


def test_canonical_fingerprint_remix_and_version_distinguish() -> None:
    original = canonical_fingerprint("M83", "Midnight City")
    remix = canonical_fingerprint("M83", "Midnight City", remix="Eric Prydz")
    live = canonical_fingerprint("M83", "Midnight City", version="Live")
    assert len({original, remix, live}) == 3
    assert remix == "m83::midnight-city::eric-prydz::original"
    assert live == "m83::midnight-city::::live"


def test_canonical_fingerprint_ampersand_folds_to_and() -> None:
    assert canonical_fingerprint("Above & Beyond", "Sun & Moon") == (
        "above-and-beyond::sun-and-moon::::original"
    )


def test_source_ref_domain_key_round_trip() -> None:
    ref = SourceRef(schema="yt", external_id="dQw4w9WgXcQ", url="https://youtu.be/x")
    assert ref.domain_key() == "yt:dQw4w9WgXcQ"
    back = SourceRef.from_domain_key("yt:dQw4w9WgXcQ")
    assert back.schema == "yt"
    assert back.external_id == "dQw4w9WgXcQ"


def test_source_ref_domain_key_preserves_colons_in_external_id() -> None:
    # discogs uses path-ish ids; only the FIRST colon separates the schema.
    back = SourceRef.from_domain_key("discogs:master/12345")
    assert back.schema == "discogs"
    assert back.external_id == "master/12345"


def test_work_key_from_fingerprint_prefix() -> None:
    fp = canonical_fingerprint("M83", "Midnight City")
    assert work_key_from_fingerprint(fp) == f"fp:{fp}"
    # wikidata-anchored keys are schema-prefixed the same way — no schema is special
    assert SourceRef(schema="wd", external_id="Q130464775").domain_key() == "wd:Q130464775"
