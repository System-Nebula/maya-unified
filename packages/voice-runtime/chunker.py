"""Sentence/clause chunking for streaming TTS.

The latency trick: don't wait for the full LLM answer. Flush a chunk to TTS as
soon as we hit a sentence boundary (or the buffer gets long), so synthesis (and
playback) can start while the model keeps generating.
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

from config import CONFIG, ChunkConfig

# A sentence boundary: . ! ? possibly followed by closing quotes/brackets, then
# whitespace or end-of-buffer.
_BOUNDARY = re.compile(r'[.!?]+["\')\]]?(\s|$)')

# Common abbreviations that end in "." but are NOT sentence ends.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e",
    "fig", "inc", "ltd", "no", "dept", "approx",
}


def _looks_like_abbreviation(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped.endswith("."):
        return False
    last = stripped.split()[-1].rstrip(".").lower()
    return last in _ABBREVIATIONS


def sentence_chunks(
    token_stream: Iterable[str],
    cfg: ChunkConfig | None = None,
) -> Iterator[str]:
    """Yield speakable chunks from a stream of text tokens/deltas."""
    cfg = cfg or CONFIG.chunk
    buffer = ""

    for token in token_stream:
        if not token:
            continue
        buffer += token

        # Flush on a sentence boundary, unless it's an abbreviation or too short.
        match = _BOUNDARY.search(buffer)
        if (
            match
            and len(buffer.strip()) >= cfg.min_chars
            and not _looks_like_abbreviation(buffer[: match.end()])
        ):
            end = match.end()
            chunk = buffer[:end].strip()
            buffer = buffer[end:]
            if chunk:
                yield chunk
            continue

        # Hard flush on length: break at the last word boundary to avoid mid-word cuts.
        if len(buffer) >= cfg.max_chars:
            cut = buffer.rfind(" ", 0, cfg.max_chars)
            if cut <= 0:
                cut = cfg.max_chars
            chunk = buffer[:cut].strip()
            buffer = buffer[cut:]
            if chunk:
                yield chunk

    if buffer.strip():
        yield buffer.strip()
