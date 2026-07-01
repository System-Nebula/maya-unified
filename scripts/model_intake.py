#!/usr/bin/env python3
"""Poll Hugging Face Hub for new model releases and upsert into the registry."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from maya_contracts import (
    CapabilityFamily,
    ModelRelease,
    ModelReleaseCreate,
    Modality,
)

HF_API = "https://huggingface.co/api"

# Rough mapping from HF pipeline_tag to our capability families
_PIPELINE_MAP: dict[str, CapabilityFamily] = {
    "text-generation": CapabilityFamily.TEXT_GENERATION,
    "text2text-generation": CapabilityFamily.TEXT_GENERATION,
    "feature-extraction": CapabilityFamily.TEXT_EMBEDDING,
    "sentence-similarity": CapabilityFamily.TEXT_EMBEDDING,
    "text-to-image": CapabilityFamily.IMAGE_GENERATION,
    "text-to-speech": CapabilityFamily.TTS,
    "visual-question-answering": CapabilityFamily.VISION_LANGUAGE,
    "image-to-text": CapabilityFamily.VISION_LANGUAGE,
}

# Tags we care about for intake
WATCHED_TAGS: set[str] = {
    "text-generation",
    "feature-extraction",
    "sentence-similarity",
    "text-to-image",
    "text-to-speech",
}


def hf_get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{HF_API}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    token = os.environ.get("HF_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = httpx.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def discover_models(
    limit: int = 50,
    sort: str = "createdAt",
    direction: str = "desc",
    pipeline_tag: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "limit": limit,
        "sort": sort,
        "direction": direction,
        "full": "false",
    }
    if pipeline_tag:
        params["filter"] = pipeline_tag
    return hf_get("/models", params)


def parse_model(raw: dict[str, Any]) -> ModelReleaseCreate | None:
    """Convert a HF model listing into our schema."""
    model_id = raw.get("modelId")
    if not model_id:
        return None

    tags: list[str] = raw.get("tags", [])
    pipeline_tag = raw.get("pipeline_tag")
    capability = _PIPELINE_MAP.get(pipeline_tag) if pipeline_tag else None
    if not capability:
        # Try to infer from tags
        for t in tags:
            if t in _PIPELINE_MAP:
                capability = _PIPELINE_MAP[t]
                break
    if not capability:
        return None  # Skip models we cannot classify

    modality_in: list[Modality] = []
    modality_out: list[Modality] = []

    if capability == CapabilityFamily.TEXT_GENERATION:
        modality_in = [Modality.TEXT]
        modality_out = [Modality.TEXT]
    elif capability == CapabilityFamily.TEXT_EMBEDDING:
        modality_in = [Modality.TEXT]
        modality_out = [Modality.TEXT]
    elif capability == CapabilityFamily.IMAGE_GENERATION:
        modality_in = [Modality.TEXT]
        modality_out = [Modality.IMAGE]
    elif capability == CapabilityFamily.TTS:
        modality_in = [Modality.TEXT]
        modality_out = [Modality.AUDIO]
    elif capability == CapabilityFamily.VISION_LANGUAGE:
        modality_in = [Modality.IMAGE, Modality.TEXT]
        modality_out = [Modality.TEXT]

    return ModelReleaseCreate(
        slug=model_id,
        provider="huggingface",
        source_url=f"https://huggingface.co/{model_id}",
        capability_family=capability,
        modality_in=modality_in,
        modality_out=modality_out,
        base_model=raw.get("config", {}).get("model_type") if raw.get("config") else None,
        license=raw.get("license"),
        tags=tags,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll HF Hub and emit registry entries")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--pipeline", type=str, default=None)
    parser.add_argument("--jsonl", action="store_true", help="Print JSONL to stdout")
    parser.add_argument("--dry-run", action="store_true", help="Skip DB write")
    args = parser.parse_args()

    models = discover_models(limit=args.limit, pipeline_tag=args.pipeline)
    created = []
    skipped = 0

    for raw in models:
        parsed = parse_model(raw)
        if not parsed:
            skipped += 1
            continue
        created.append(parsed)

    if args.jsonl or args.dry_run:
        for c in created:
            print(c.model_dump_json())
        print(f"# emitted {len(created)}, skipped {skipped}", file=sys.stderr)
        return 0

    # Try to write to DB if available
    try:
        from maya_db import ModelRelease as ModelReleaseDB
        from maya_db import get_async_session
        import asyncio

        async def upsert() -> int:
            count = 0
            async for session in get_async_session():
                for c in created:
                    existing = await session.get(ModelReleaseDB, c.slug)
                    if existing:
                        continue
                    release = ModelReleaseDB(
                        slug=c.slug,
                        provider=c.provider,
                        source_url=c.source_url,
                        capability_family=c.capability_family.value,
                        modality_in=[m.value for m in c.modality_in],
                        modality_out=[m.value for m in c.modality_out],
                        base_model=c.base_model,
                        license=c.license,
                        tags=c.tags,
                    )
                    session.add(release)
                    count += 1
                await session.commit()
            return count

        inserted = asyncio.run(upsert())
        print(f"Inserted {inserted} new releases, skipped {skipped}")
    except Exception as e:
        print(f"DB write failed: {e}", file=sys.stderr)
        print("Use --jsonl to inspect without DB", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
