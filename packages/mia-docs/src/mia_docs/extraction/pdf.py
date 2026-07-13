"""PDF text extraction via pymupdf, streamed page by page."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class PageText:
    page_no: int  # 1-based
    text: str


def doc_hash(pdf_path: str | Path) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pages(pdf_path: str | Path) -> Iterator[PageText]:
    import fitz

    with fitz.open(str(pdf_path)) as doc:
        for i, page in enumerate(doc):
            yield PageText(page_no=i + 1, text=page.get_text("text"))


def text_coverage(pdf_path: str | Path, sample_pages: int = 10) -> float:
    """Fraction of sampled pages that have a usable text layer.

    Low coverage means the PDF is scanned/raster and needs an OCR pre-pass
    (ocrmypdf) before ingest — OCR is outside sk mine by design.
    """
    import fitz

    with fitz.open(str(pdf_path)) as doc:
        n = min(sample_pages, len(doc))
        if n == 0:
            return 0.0
        with_text = sum(
            1 for i in range(n) if len(doc[i].get_text("text").strip()) > 40
        )
        return with_text / n
