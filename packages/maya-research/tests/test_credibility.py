"""Tests for domain credibility scoring."""

from maya_research.tools.credibility import score_domain


def test_edu_domain_scores_high():
    assert score_domain("https://cs.stanford.edu/paper") >= 0.85


def test_github_scores_high():
    assert score_domain("https://github.com/org/repo") >= 0.8


def test_unknown_domain_default():
    assert 0.4 <= score_domain("https://example.com/page") <= 0.6
