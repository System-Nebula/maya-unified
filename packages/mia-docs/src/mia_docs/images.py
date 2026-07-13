"""Image extraction + CLIP indexing for source PDFs.

Same principles as text ingest: deterministic (id = sha256 of image bytes),
no LLM on the write path — CLIP is a fixed local encoder. clip-ViT-B-32
embeds images and text into the same 512-d space, so `sk find-image` is a
text query against image vectors.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, text

from maya_db.models import AtomicNote, NoteImage
from mia_docs.extraction.pdf import doc_hash
from mia_docs.store import get_session

MIN_DIM = 200  # skip icons/decoration
MAX_BOILERPLATE_PAGES = 3  # same image on many pages = logo/watermark
_clip = None
_clip_failed = False


def _load_clip():
    global _clip, _clip_failed
    if _clip is not None or _clip_failed:
        return _clip
    try:
        from sentence_transformers import SentenceTransformer

        _clip = SentenceTransformer("clip-ViT-B-32")
    except Exception:
        _clip_failed = True
    return _clip


def embed_images(images) -> list[list[float]] | None:
    model = _load_clip()
    if model is None:
        return None
    return [
        list(map(float, v))
        for v in model.encode(images, normalize_embeddings=True)
    ]


def embed_query(query: str) -> list[float] | None:
    model = _load_clip()
    if model is None:
        return None
    return list(map(float, model.encode([query], normalize_embeddings=True)[0]))


@dataclass
class ImageIngestReport:
    source: str
    extracted: int = 0
    skipped_small: int = 0
    skipped_boilerplate: int = 0
    linked: int = 0


def _page_note_map(session, source_hash: str) -> list[tuple[int, int, str]]:
    rows = session.execute(
        select(AtomicNote.page_start, AtomicNote.page_end, AtomicNote.id).where(
            AtomicNote.source_doc_hash == source_hash,
            AtomicNote.note_type == "recipe",
        )
    ).all()
    return [(ps, pe, nid) for ps, pe, nid in rows if ps is not None]


def _note_for_page(ranges: list[tuple[int, int, str]], page_no: int) -> str | None:
    for ps, pe, nid in ranges:
        if ps <= page_no <= pe:
            return nid
    return None


def ingest_images(
    pdf_path: str | Path,
    media_dir: str | Path = "docs/content/Recipes/media",
    session=None,
) -> ImageIngestReport:
    import fitz
    from PIL import Image

    pdf_path = Path(pdf_path)
    media = Path(media_dir)
    media.mkdir(parents=True, exist_ok=True)
    report = ImageIngestReport(source=str(pdf_path))
    source_hash = doc_hash(pdf_path)

    own_session = session is None
    session = session or get_session()
    try:
        ranges = _page_note_map(session, source_hash)

        # first pass: collect candidates, counting pages per image hash
        candidates: dict[str, dict] = {}
        pages_seen: dict[str, set[int]] = {}
        with fitz.open(str(pdf_path)) as doc:
            for page_index in range(len(doc)):
                page_no = page_index + 1
                for xref, *_ in doc[page_index].get_images(full=True):
                    try:
                        info = doc.extract_image(xref)
                    except Exception:
                        continue
                    if info["width"] < MIN_DIM or info["height"] < MIN_DIM:
                        report.skipped_small += 1
                        continue
                    img_id = hashlib.sha256(info["image"]).hexdigest()
                    pages_seen.setdefault(img_id, set()).add(page_no)
                    if img_id not in candidates:
                        candidates[img_id] = {
                            "bytes": info["image"],
                            "ext": info["ext"],
                            "width": info["width"],
                            "height": info["height"],
                            "page_no": page_no,
                        }

        keep = {
            k: v
            for k, v in candidates.items()
            if len(pages_seen[k]) <= MAX_BOILERPLATE_PAGES
        }
        report.skipped_boilerplate = len(candidates) - len(keep)

        ids = list(keep)
        pil_images = []
        for img_id in ids:
            pil_images.append(Image.open(io.BytesIO(keep[img_id]["bytes"])).convert("RGB"))
        vectors = embed_images(pil_images) if pil_images else []

        for i, img_id in enumerate(ids):
            cand = keep[img_id]
            path = media / f"{img_id[:16]}.{cand['ext']}"
            if not path.exists():
                path.write_bytes(cand["bytes"])
            note_id = _note_for_page(ranges, cand["page_no"])
            if note_id:
                report.linked += 1
            existing = session.get(NoteImage, img_id)
            if existing is None:
                session.add(
                    NoteImage(
                        id=img_id,
                        note_id=note_id,
                        source_doc_hash=source_hash,
                        page_no=cand["page_no"],
                        path=str(path),
                        width=cand["width"],
                        height=cand["height"],
                        embedding=vectors[i] if vectors else None,
                    )
                )
            elif existing.embedding is None and vectors:
                existing.embedding = vectors[i]
            report.extracted += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()
    return report


def search_images(query: str, top_k: int = 5, session=None) -> list[dict]:
    qv = embed_query(query)
    if qv is None:
        raise RuntimeError("CLIP model unavailable (install mia-docs[embed])")
    own_session = session is None
    session = session or get_session()
    try:
        sql = text(
            """
            SELECT i.id, i.path, i.page_no, i.note_id, n.title,
                   1 - (i.embedding <=> CAST(:qv AS vector)) AS score
            FROM kb_note_images i
            LEFT JOIN kb_atomic_notes n ON n.id = i.note_id
            WHERE i.embedding IS NOT NULL
            ORDER BY i.embedding <=> CAST(:qv AS vector)
            LIMIT :lim
            """
        )
        rows = session.execute(
            sql,
            {"qv": "[" + ",".join(f"{x:.8f}" for x in qv) + "]", "lim": top_k},
        ).all()
        return [
            {
                "id": r.id,
                "path": r.path,
                "page_no": r.page_no,
                "recipe": r.title,
                "note_id": r.note_id,
                "score": round(float(r.score), 4),
            }
            for r in rows
        ]
    finally:
        if own_session:
            session.close()
