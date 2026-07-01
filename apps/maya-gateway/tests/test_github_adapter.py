"""Tests for GitHub release adapter and API helpers."""

from maya_feeds.github_api import (
    chunk_patches,
    extract_tag_from_release_url,
    parse_repo_slug,
    relevant_files,
    CompareFile,
)


def test_parse_repo_slug_from_handle():
    owner, repo = parse_repo_slug("nix-community/lanzaboote")
    assert owner == "nix-community"
    assert repo == "lanzaboote"


def test_parse_repo_slug_from_url():
    owner, repo = parse_repo_slug("https://github.com/nix-community/lanzaboote/releases.atom")
    assert owner == "nix-community"
    assert repo == "lanzaboote"


def test_extract_tag_from_release_url():
    url = "https://github.com/nix-community/lanzaboote/releases/tag/v1.0.0"
    assert extract_tag_from_release_url(url) == "v1.0.0"


def test_relevant_files_filters_lock_and_tests():
    files = [
        CompareFile("src/main.rs", "modified", 10, 2, "+fn main()"),
        CompareFile("Cargo.lock", "modified", 100, 50, "+version"),
        CompareFile("tests/integration.rs", "added", 20, 0, "+#[test]"),
        CompareFile("README.md", "modified", 5, 1, "+docs"),
        CompareFile("binary.png", "added", 0, 0, None),
    ]
    out = relevant_files(files)
    assert len(out) == 2
    assert {f.filename for f in out} == {"src/main.rs", "README.md"}


def test_chunk_patches_splits_large_sets():
    files = [
        CompareFile(f"f{i}.rs", "modified", 1, 0, "x" * 10000) for i in range(5)
    ]
    chunks = chunk_patches(files, max_chars=15000)
    assert len(chunks) >= 2


def test_github_adapter_slug_normalization():
    owner, repo = parse_repo_slug("foo/bar")
    assert f"{owner}/{repo}" == "foo/bar"
