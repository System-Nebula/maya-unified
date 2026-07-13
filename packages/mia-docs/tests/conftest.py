from pathlib import Path

import pytest

from mia_docs.extraction.pdf import PageText

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_pages() -> list[PageText]:
    raw = (FIXTURES / "recipes_sample.txt").read_text()
    return [
        PageText(page_no=i + 1, text=chunk)
        for i, chunk in enumerate(raw.split("<<<PAGE>>>"))
    ]
