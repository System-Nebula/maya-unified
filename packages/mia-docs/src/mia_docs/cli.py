"""sk CLI: deterministic mine, hybrid query, vault materializer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="AtomicNote knowledge base (mia-docs)")


@app.command()
def mine(
    path: Path = typer.Argument(..., exists=True, help="Source PDF"),
    type: str = typer.Option("recipe", "--type", help="note_type to extract"),
    images: bool = typer.Option(
        False, "--images", help="also extract + CLIP-index page images"
    ),
    media_dir: Path = typer.Option(
        Path("docs/content/Recipes/media"), "--media-dir"
    ),
) -> None:
    """Extract a document into AtomicNotes. Zero LLM calls on the write path."""
    from mia_docs.ingest import ingest_pdf

    if type != "recipe":
        typer.echo(f"note_type {type!r} has no extractor yet", err=True)
        raise typer.Exit(2)
    report = ingest_pdf(path, note_type=type)
    image_report = None
    if images:
        from mia_docs.images import ingest_images

        image_report = ingest_images(path, media_dir=media_dir)
    if report.text_coverage < 0.5:
        typer.echo(
            f"warning: only {report.text_coverage:.0%} of sampled pages have a "
            "text layer — run an OCR pre-pass (ocrmypdf --skip-text) first",
            err=True,
        )
    payload = {
        "source": report.source,
        "recipes": report.recipes,
        "low_confidence": report.low_confidence,
        "ingredient_links": report.ingredients,
        "technique_links": report.techniques,
        "related_edges": report.related_edges,
    }
    if image_report is not None:
        payload["images"] = {
            "extracted": image_report.extracted,
            "linked_to_recipes": image_report.linked,
            "skipped_small": image_report.skipped_small,
            "skipped_boilerplate": image_report.skipped_boilerplate,
        }
    typer.echo(json.dumps(payload, indent=2))


@app.command()
def query(
    text: str = typer.Argument(..., help="Natural-language query"),
    type: Optional[str] = typer.Option("recipe", "--type"),
    label: list[str] = typer.Option([], "--label", help="e.g. cuisine:italian"),
    filter: list[str] = typer.Option(
        [], "--filter", help="e.g. metadata.servings<=4"
    ),
    rerank: bool = typer.Option(False, "--rerank"),
    expand_links: int = typer.Option(0, "--expand-links"),
    top_k: int = typer.Option(10, "--top-k"),
) -> None:
    """Hybrid retrieval: SQL prune -> vector recall -> rerank -> graph expand."""
    from mia_docs.retrieval import search

    hits = search(
        text,
        note_type=type,
        labels=label or None,
        filters=filter or None,
        rerank=rerank,
        expand_links=expand_links,
        top_k=top_k,
    )
    out = []
    for h in hits:
        out.append(
            {
                "id": h.note.id,
                "title": h.note.title,
                "score": round(h.score, 4),
                "note_type": h.note.note_type,
                "meta": {
                    k: v
                    for k, v in (h.note.meta or {}).items()
                    if k in ("servings", "prep_min", "cook_min", "page_range", "extraction_confidence")
                },
                "linked": h.linked,
            }
        )
    typer.echo(json.dumps(out, indent=2))


@app.command("find-image")
def find_image(
    text: str = typer.Argument(..., help="Text description of the image"),
    top_k: int = typer.Option(5, "--top-k"),
) -> None:
    """Text-to-image search over CLIP-indexed cookbook images."""
    from mia_docs.images import search_images

    typer.echo(json.dumps(search_images(text, top_k=top_k), indent=2))


@app.command()
def materialize(
    out: Path = typer.Option(
        Path("docs/content/Recipes"), "--out", help="Vault output directory"
    ),
    type: str = typer.Option("recipe", "--type"),
) -> None:
    """Render notes to the Quartz vault (read-only surface, idempotent)."""
    from mia_docs.materialize import materialize_vault

    result = materialize_vault(out, note_type=type)
    typer.echo(json.dumps(result))


if __name__ == "__main__":
    app()
