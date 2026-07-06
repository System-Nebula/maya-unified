"""MDX + capture.json manifest writer for processed browser captures."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from services.browser.config import MAYA_CAPTURE_MDX_ROOT, PIPELINE_VERSION


def _slugify(title: str, capture_id: str) -> str:
    base = title.strip().lower() if title.strip() else capture_id[:8]
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return slug[:80] or capture_id[:8]


def capture_dir(capture_type: str, slug: str) -> Path:
    path = MAYA_CAPTURE_MDX_ROOT / capture_type / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_capture_artifacts(
    *,
    capture_id: str,
    capture_type: str,
    url: str,
    title: str,
    content_hash: str,
    tags: list[str],
    reader_text: str,
    selection: str,
    assets: list[dict[str, Any]],
    metadata: dict[str, Any],
    received_at: datetime | None = None,
) -> tuple[Path, Path]:
    """Write page.mdx and capture.json; return paths."""
    slug = _slugify(title, capture_id)
    out_dir = capture_dir(capture_type, slug)
    mdx_path = out_dir / "page.mdx"
    manifest_path = out_dir / "capture.json"

    saved = (received_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    host = urlparse(url).netloc or "web"
    attachment_lines = "\n".join(f"  - {a.get('key', '')}" for a in assets)

    frontmatter = f"""---
title: {json.dumps(title or url)}
url: {json.dumps(url)}
saved: {saved}
capture_id: {capture_id}
content_hash: {content_hash}
source: {json.dumps(host)}
tags:
"""
    for tag in tags:
        frontmatter += f"  - {json.dumps(tag)}\n"
    if not tags:
        frontmatter += "  - generic\n"

    frontmatter += f"""entities: []
embedding: false
attachments:
{attachment_lines if attachment_lines else "  []"}
relationships:
  saved_from: chrome
---

# Summary

{(reader_text or selection or title or url)[:2000]}

# Highlights

{(selection or "")[:4000]}

# Notes



# Quotes



# Images



# Metadata

```json
{json.dumps(metadata, indent=2)}
```
"""

    mdx_path.write_text(frontmatter, encoding="utf-8")

    manifest = {
        "capture_id": capture_id,
        "content_hash": content_hash,
        "capture_type": capture_type,
        "url": url,
        "title": title,
        "pipeline_version": PIPELINE_VERSION,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "assets": assets,
        "mdx_path": str(mdx_path.relative_to(MAYA_CAPTURE_MDX_ROOT)),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return mdx_path, manifest_path
