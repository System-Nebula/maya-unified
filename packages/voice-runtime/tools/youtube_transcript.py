"""Fetch YouTube captions so Maya can summarize videos in character.

Ported from System-Nebula/daddai ``youtube_transcript_tool``. Long transcripts
are optionally smart-chunked via ``transcript_chunker`` (no document-store/RAG).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

log = logging.getLogger("tools.youtube_transcript")

# When full transcript exceeds this, run multi-pass smart summarization.
_SMART_SUMMARY_MIN_CHARS = 5000

_DEFAULT_LANGS = ("en", "en-US", "en-GB", "en-CA", "en-AU")

_YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
_YT_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:[^&\s]*&)*v=|embed/|shorts/)|youtu\.be/)"
    r"([a-zA-Z0-9_-]{11})",
    re.I,
)


def extract_video_id(url_or_id: str) -> str | None:
    """Extract an 11-char YouTube video ID from a URL or bare ID."""
    raw = (url_or_id or "").strip()
    if not raw:
        return None
    if _YT_ID_RE.match(raw):
        return raw
    match = _YT_URL_RE.search(raw)
    if match:
        return match.group(1)
    # Fallback patterns (query-string edge cases)
    for pattern in (
        r"youtube\.com/watch\?.*?\bv=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
    ):
        m = re.search(pattern, raw, re.I)
        if m:
            return m.group(1)
    return None


def extract_youtube_url(text: str) -> str | None:
    """Find the first YouTube URL or bare video ID in free text."""
    raw = (text or "").strip()
    if not raw:
        return None
    match = _YT_URL_RE.search(raw)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    # Bare ID only when the whole token looks like one
    for token in re.split(r"\s+", raw):
        token = token.strip(".,!?;:()'\"")
        if _YT_ID_RE.match(token):
            return f"https://www.youtube.com/watch?v={token}"
    return None


def find_latest_youtube_url(messages: list[dict] | None) -> str | None:
    """Return the newest YouTube URL found in Discord message snippets.

    ``messages`` are expected oldest→newest (as ``discord_read_channel`` returns).
    """
    if not messages:
        return None
    for msg in reversed(list(messages)):
        if not isinstance(msg, dict):
            continue
        url = extract_youtube_url(str(msg.get("content") or ""))
        if url:
            return url
    return None


def _snippet_rows(fetched: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snippet in fetched:
        if isinstance(snippet, dict):
            text = str(snippet.get("text") or "").strip()
            start = float(snippet.get("start") or 0.0)
            duration = float(snippet.get("duration") or 0.0)
        else:
            text = str(getattr(snippet, "text", "") or "").strip()
            start = float(getattr(snippet, "start", 0.0) or 0.0)
            duration = float(getattr(snippet, "duration", 0.0) or 0.0)
        if text:
            rows.append({"text": text, "start": start, "duration": duration})
    return rows


def _fetch_via_list_api(video_id: str, language_codes: list[str]) -> tuple[list[dict], str]:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    for lang_code in language_codes:
        try:
            transcript = transcript_list.find_transcript([lang_code])
            rows = _snippet_rows(transcript.fetch())
            if rows:
                return rows, lang_code
        except (NoTranscriptFound, TranscriptsDisabled):
            continue
        except Exception as exc:  # noqa: BLE001
            log.debug("transcript lang %s failed: %s", lang_code, exc)
            continue

    try:
        transcript = transcript_list.find_manually_created_transcript(["en"])
        rows = _snippet_rows(transcript.fetch())
        if rows:
            return rows, "en"
    except Exception:  # noqa: BLE001
        pass

    for transcript in transcript_list:
        try:
            rows = _snippet_rows(transcript.fetch())
            if rows:
                return rows, str(getattr(transcript, "language_code", "unknown") or "unknown")
        except Exception as exc:  # noqa: BLE001
            log.debug("transcript fallback failed: %s", exc)
            continue
    return [], ""


def _fetch_via_legacy_api(video_id: str, language_codes: list[str]) -> tuple[list[dict], str]:
    from youtube_transcript_api import YouTubeTranscriptApi

    get_transcript = getattr(YouTubeTranscriptApi, "get_transcript", None)
    if not callable(get_transcript):
        return [], ""
    try:
        raw = get_transcript(video_id, languages=language_codes)
        rows = _snippet_rows(raw)
        if rows:
            return rows, language_codes[0] if language_codes else "en"
    except Exception as exc:  # noqa: BLE001
        log.debug("legacy get_transcript failed: %s", exc)
    return [], ""


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    text = (text or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head = max(400, int(max_chars * 0.65))
    tail = max(200, max_chars - head - 40)
    clipped = (
        text[:head].rstrip()
        + "\n\n[…transcript truncated for length…]\n\n"
        + text[-tail:].lstrip()
    )
    return clipped, True


def youtube_transcript(
    url: str,
    *,
    max_chars: int = 10000,
    language_codes: list[str] | None = None,
    smart_summarize: bool = True,
    video_title: str = "",
    focus: str = "",
    llm_complete: Optional[Callable[[list[dict[str, str]], int], str]] = None,
) -> dict[str, Any]:
    """Fetch caption text for a YouTube URL / video ID.

    Returns a dict the LLM can summarize in personality. Never plays audio.
    When ``smart_summarize`` is True and the full transcript is long, also
    attaches ``smart_summary`` via time-based chunking + multi-pass LLM merge.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # noqa: F401
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
        )
    except ImportError:
        return {
            "ok": False,
            "error": (
                "youtube-transcript-api is not installed. "
                "Install with: uv add youtube-transcript-api"
            ),
            "url": url,
        }

    video_id = extract_video_id(url)
    if not video_id:
        return {
            "ok": False,
            "error": f"Could not extract a YouTube video ID from: {url}",
            "url": url,
        }

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    langs = list(language_codes or _DEFAULT_LANGS)

    try:
        rows, language_used = _fetch_via_list_api(video_id, langs)
        if not rows:
            rows, language_used = _fetch_via_legacy_api(video_id, langs)
        if not rows:
            return {
                "ok": False,
                "error": (
                    f"No transcript available for video {video_id}. "
                    "Captions may be disabled or unavailable."
                ),
                "url": video_url,
                "video_id": video_id,
                "tried_languages": langs,
            }

        parts = [r["text"] for r in rows if r.get("text")]
        transcript_text = " ".join(parts).strip()
        if len(transcript_text) < 10:
            return {
                "ok": False,
                "error": "Transcript is empty or too short",
                "url": video_url,
                "video_id": video_id,
            }

        clipped, truncated = _truncate(transcript_text, int(max_chars or 10000))
        out: dict[str, Any] = {
            "ok": True,
            "url": video_url,
            "video_id": video_id,
            "language": language_used or "unknown",
            "transcript": clipped,
            "transcript_length": len(transcript_text),
            "chars_returned": len(clipped),
            "num_segments": len(rows),
            "truncated": truncated,
            "note": (
                "Summarize this transcript in your personality for the user. "
                "Do not read it verbatim or recite URLs."
            ),
        }

        if smart_summarize and len(transcript_text) >= _SMART_SUMMARY_MIN_CHARS:
            try:
                from tools.transcript_chunker import smart_summarize_transcript

                smart = smart_summarize_transcript(
                    transcript_text,
                    transcript_segments=rows,
                    video_title=video_title or "",
                    focus=focus or "",
                    complete=llm_complete,
                    min_chars_for_chunking=_SMART_SUMMARY_MIN_CHARS,
                )
                if smart.get("ok") and (smart.get("summary") or "").strip():
                    out["smart_summary"] = smart["summary"]
                    out["smart_summary_method"] = smart.get("method")
                    out["smart_summary_chunks"] = smart.get("num_chunks")
                    out["note"] = (
                        "A smart_summary is already included for this long transcript. "
                        "Rewrite that summary in your personality for the user. "
                        "Do not read the raw transcript verbatim or recite URLs."
                    )
                else:
                    out["smart_summary_error"] = smart.get("error") or "smart summary empty"
            except Exception as exc:  # noqa: BLE001
                log.warning("smart transcript summary failed: %s", exc)
                out["smart_summary_error"] = str(exc)

        return out
    except VideoUnavailable:
        return {
            "ok": False,
            "error": "Video is unavailable or has been removed",
            "url": video_url,
            "video_id": video_id,
        }
    except TranscriptsDisabled:
        return {
            "ok": False,
            "error": "Transcripts are disabled for this video",
            "url": video_url,
            "video_id": video_id,
        }
    except NoTranscriptFound:
        return {
            "ok": False,
            "error": "No transcript found for this video",
            "url": video_url,
            "video_id": video_id,
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("youtube transcript failed for %s", video_id)
        return {
            "ok": False,
            "error": f"Failed to fetch transcript: {exc}",
            "url": video_url,
            "video_id": video_id,
        }
