"""Unit tests for browser capture helpers."""

from maya_contracts import CaptureEvent

from services.browser.hashing import compute_content_hash


def test_content_hash_stable() -> None:
    event = CaptureEvent(
        capture_type="article",
        url="https://example.com",
        reader_text="hello",
        selection="world",
    )
    a = compute_content_hash(event)
    b = compute_content_hash(event)
    assert a == b
    assert len(a) == 64


def test_content_hash_changes_with_selection() -> None:
    base = CaptureEvent(capture_type="article", url="https://example.com", reader_text="x")
    other = CaptureEvent(
        capture_type="article",
        url="https://example.com",
        reader_text="x",
        selection="different",
    )
    assert compute_content_hash(base) != compute_content_hash(other)
