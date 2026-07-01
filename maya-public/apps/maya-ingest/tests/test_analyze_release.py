"""Tests for release analysis helpers."""

from maya_feeds.github_api import CompareFile, chunk_patches, relevant_files


def test_relevant_files_respects_custom_ignore_patterns():
    files = [
        CompareFile("docs/guide.md", "modified", 3, 1, "+text"),
        CompareFile("vendor/deps.txt", "modified", 1, 0, "+dep"),
    ]
    out = relevant_files(files, ignore_patterns=[r"^vendor/"])
    assert len(out) == 1
    assert out[0].filename == "docs/guide.md"


def test_chunk_patches_empty():
    assert chunk_patches([]) == [[]]
