"""Materialize AtomicNotes to the Quartz vault as a read-only surface.

Never hand-edit the generated files — the KG is the source of truth; the
vault is an ephemeral render keyed on content hash (idempotent re-runs).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import select

from maya_db.models import AtomicNote
from mia_docs.predicates import Predicate
from mia_docs.store import get_session, neighbors

_HASH_RE = re.compile(r"^content_hash:\s*(\S+)$", re.MULTILINE)


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "untitled"


def render_note(note: AtomicNote, edges: list, image_file: str | None = None) -> str:
    lines = [
        "---",
        f"id: {note.id}",
        f"title: \"{note.title}\"",
        f"note_type: {note.note_type}",
        f"labels: {note.labels or []}",
        f"version: {note.version}",
        "generated: true",
        "---",
        "",
        f"# {note.title}",
        "",
    ]
    if image_file:
        lines += [f"![{note.title}](media/{image_file})", ""]
    meta = note.meta or {}
    facts = [
        f"- **{k.replace('_', ' ').title()}:** {meta[k]}"
        for k in ("servings", "prep_min", "cook_min")
        if meta.get(k) is not None
    ]
    if facts:
        lines += facts + [""]

    contains = [(e, n) for e, n in edges if e.predicate == Predicate.CONTAINS.value]
    employs = [(e, n) for e, n in edges if e.predicate == Predicate.EMPLOYS.value]
    related = [(e, n) for e, n in edges if e.predicate == Predicate.RELATED_TO.value]
    if contains:
        lines.append("## Ingredients")
        for edge, n in contains:
            qty = " ".join(x for x in [edge.meta.get("quantity"), edge.meta.get("unit")] if x)
            suffix = f" — {qty}" if qty else ""
            lines.append(f"- [[Ingredient/{n.title}]]{suffix}")
        lines.append("")
    if employs:
        lines.append(
            "**Techniques:** "
            + ", ".join(f"[[Technique/{n.title}]]" for _, n in employs)
        )
        lines.append("")
    lines += ["## Source Text", "", "```", note.content, "```", ""]
    if related:
        lines.append("## Related")
        for _, n in related:
            lines.append(f"- [[{slugify(n.title)}|{n.title}]]")
        lines.append("")
    return "\n".join(lines)


def materialize_vault(out_dir: str | Path, note_type: str = "recipe") -> dict[str, int]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    session = get_session()
    try:
        notes = session.execute(
            select(AtomicNote)
            .where(AtomicNote.note_type == note_type)
            .order_by(AtomicNote.id)
        ).scalars().all()
        edge_map = neighbors(
            session, [n.id for n in notes], cap_per_note=100
        )
        from maya_db.models import NoteImage

        image_map: dict[str, str] = {}
        for img in session.execute(
            select(NoteImage)
            .where(NoteImage.note_id.in_([n.id for n in notes]))
            .order_by(NoteImage.note_id, NoteImage.page_no, NoteImage.id)
        ).scalars():
            image_map.setdefault(img.note_id, Path(img.path).name)

        used_slugs: set[str] = set()
        for note in notes:
            body = render_note(
                note, edge_map.get(note.id, []), image_map.get(note.id)
            )
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
            rendered = body.replace(
                "generated: true", f"generated: true\ncontent_hash: {content_hash}"
            )
            slug = slugify(note.title)
            if slug in used_slugs:
                slug = f"{slug}-{note.id[:8]}"
            used_slugs.add(slug)
            path = out / f"{slug}.md"
            if path.exists():
                m = _HASH_RE.search(path.read_text())
                if m and m.group(1) == content_hash:
                    skipped += 1
                    continue
            path.write_text(rendered)
            written += 1
    finally:
        session.close()
    return {"written": written, "skipped": skipped}
