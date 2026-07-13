"""Deterministic note identifiers (provenance hashes)."""

from __future__ import annotations

import hashlib


def note_id(block_text: str, source_doc_hash: str, page_range: tuple[int, int]) -> str:
    """sha256 of (raw block text + source document hash + page range).

    Re-running ingest on the same source yields the same id, so writes
    upsert/version-bump rather than duplicate.
    """
    h = hashlib.sha256()
    h.update(block_text.encode("utf-8"))
    h.update(source_doc_hash.encode("ascii"))
    h.update(f"{page_range[0]}-{page_range[1]}".encode("ascii"))
    return h.hexdigest()


def entity_id(note_type: str, canonical_name: str) -> str:
    """Deterministic id for ingredient/technique notes keyed by canonical name."""
    return hashlib.sha256(f"{note_type}:{canonical_name}".encode("utf-8")).hexdigest()
