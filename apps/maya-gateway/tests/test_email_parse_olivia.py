"""Tests for Olivia Rodrigo newsletter email parsing."""

from maya_gateway.services.email_parse import parse_email_newsletter

OLIVIA_HTML = """
<html><head><meta name="theme-color" content="#ec4899"></head><body>
<h1>Olivia Rodrigo</h1>
<p>you seem pretty sad for a girl so in love</p>
<p>handwritten note from me</p>
<p>"what's wrong with me" ft. Robert Smith (The Cure)</p>
<p>first feature I've ever done on an album</p>
<p>Exclusive lenticular cover vinyl pre-order</p>
</body></html>
"""


def test_parse_olivia_rodrigo_newsletter():
    parsed = parse_email_newsletter(
        from_header="Olivia Rodrigo <news@oliviarodrigo.umusic-online.com>",
        subject="New music from Olivia Rodrigo",
        html=OLIVIA_HTML,
        date_header="Sun, 08 Jun 2025 18:12:00 +0000",
    )
    assert parsed.artist_slug == "olivia-rodrigo"
    assert parsed.artist_display == "Olivia Rodrigo"
    assert parsed.source == "oliviarodrigo.umusic-online.com"
    assert "music" in parsed.tags
    assert "new_release" in parsed.tags
    assert parsed.handwritten_note is True
    assert parsed.album == "you seem pretty sad for a girl so in love"
    assert parsed.track is not None
    assert "Robert Smith" in parsed.track
    assert parsed.brand_color == "#ec4899"
    assert parsed.promo is not None
