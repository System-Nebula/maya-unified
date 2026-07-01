"""Tests for YouTube description intel extraction."""

from maya_contracts import IntelItemKind
from maya_feeds.youtube_intel import (
    classify_url,
    decode_youtube_redirect,
    extract_intel_items,
    normalize_url,
    parse_description,
    timestamp_to_seconds,
    zip_chapters_to_urls,
)

# Excerpt from AI news roundup style description (CzxqQJOswvo pattern)
FIXTURE_DESCRIPTION = """
[0:00] AI news intro
[0:55] Bernini
[3:43] Deja View
[16:00] Ideogram v4
[22:43] Gemma4 12B

Bernini https://bernini-ai.github.io/
Deja View https://research.nvidia.com/labs/dvl/projects/dvlt/
Ideogram v4 https://ideogram.ai/
Gemma4 12B https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12B/
https://github.com/org/some-repo
"""


def test_timestamp_to_seconds():
    assert timestamp_to_seconds("3:43") == 223
    assert timestamp_to_seconds("1:02:05") == 3725


def test_decode_youtube_redirect():
    url = (
        "https://www.youtube.com/redirect?event=video_description"
        "&q=https%3A%2F%2Fresearch.nvidia.com%2Flabs%2Fdvl%2Fprojects%2Fdvlt%2F"
    )
    decoded = decode_youtube_redirect(url)
    assert decoded.startswith("https://research.nvidia.com/")


def test_classify_url():
    assert classify_url("https://github.com/foo/bar") == IntelItemKind.REPO
    assert classify_url("https://arxiv.org/abs/1234.5678") == IntelItemKind.PAPER
    assert classify_url("https://example.com/page") == IntelItemKind.UNKNOWN


def test_parse_description_extracts_chapters_and_urls():
    parsed = parse_description(FIXTURE_DESCRIPTION)
    assert len(parsed["chapters"]) == 5
    assert parsed["chapters"][0]["label"] == "AI news intro"
    assert any("bernini-ai.github.io" in u for u in parsed["urls"])
    assert not any("youtube.com/redirect" in u for u in parsed["urls"])


def test_zip_chapters_to_urls_pairs_by_order():
    parsed = parse_description(FIXTURE_DESCRIPTION)
    items = zip_chapters_to_urls(parsed["chapters"], parsed["urls"])
    labeled = [i for i in items if i["url"]]
    assert labeled[0]["label"] == "Bernini"
    assert "bernini-ai.github.io" in labeled[0]["url"]


def test_extract_intel_items_full_pipeline():
    items = extract_intel_items(FIXTURE_DESCRIPTION)
    urls = [i for i in items if i.get("url")]
    assert len(urls) >= 4
    labels = {i["label"] for i in urls}
    assert "Bernini" in labels
    assert "Ideogram v4" in labels
    repo_items = [i for i in urls if i["kind"] == IntelItemKind.REPO]
    assert any("github.com" in i["url"] for i in repo_items)


def test_normalize_url_strips_trailing_slash():
    assert normalize_url("https://ideogram.ai/") == "https://ideogram.ai"
