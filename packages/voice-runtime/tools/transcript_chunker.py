"""Smart transcript chunking + multi-pass summarization (ported from daddai).

Splits long YouTube/caption transcripts into time-based overlapping chunks,
summarizes each chunk with the local LLM, then merges into a final summary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

log = logging.getLogger("tools.transcript_chunker")

# (messages, max_tokens) -> assistant text
CompleteFn = Callable[[list[dict[str, str]], int], str]


@dataclass
class TranscriptChunk:
    """A time-bounded slice of a transcript."""

    text: str
    start_time: float
    end_time: float
    chunk_index: int
    total_chunks: int

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def time_range_str(self) -> str:
        return f"{self._fmt(self.start_time)} - {self._fmt(self.end_time)}"

    @staticmethod
    def _fmt(seconds: float) -> str:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"


class TranscriptChunker:
    """Split a transcript into overlapping time-based chunks."""

    def __init__(
        self,
        chunk_duration_minutes: float = 10.0,
        overlap_minutes: float = 1.0,
        min_chunk_chars: int = 100,
    ):
        self.chunk_duration = chunk_duration_minutes * 60.0
        self.overlap = overlap_minutes * 60.0
        self.min_chunk_chars = min_chunk_chars

    def chunk_transcript(
        self,
        transcript_text: str,
        transcript_segments: list[dict] | None = None,
    ) -> list[TranscriptChunk]:
        if transcript_segments:
            return self._chunk_with_timestamps(transcript_segments)
        return self._chunk_by_estimation(transcript_text)

    def _chunk_with_timestamps(self, segments: list[dict]) -> list[TranscriptChunk]:
        if not segments:
            return []

        total_duration = 0.0
        for seg in segments:
            end = float(seg.get("start", 0) or 0) + float(seg.get("duration", 0) or 0)
            total_duration = max(total_duration, end)

        if total_duration <= self.chunk_duration:
            text = " ".join(str(s.get("text") or "") for s in segments).strip()
            return [
                TranscriptChunk(
                    text=text,
                    start_time=0.0,
                    end_time=total_duration,
                    chunk_index=0,
                    total_chunks=1,
                )
            ]

        chunks: list[TranscriptChunk] = []
        current_start = 0.0
        chunk_index = 0

        while current_start < total_duration:
            current_end = min(current_start + self.chunk_duration, total_duration)
            chunk_segments = [
                s
                for s in segments
                if float(s.get("start", 0) or 0) >= current_start
                and float(s.get("start", 0) or 0) < current_end
            ]
            if chunk_segments:
                text = " ".join(str(s.get("text") or "") for s in chunk_segments).strip()
                if len(text) >= self.min_chunk_chars:
                    chunks.append(
                        TranscriptChunk(
                            text=text,
                            start_time=current_start,
                            end_time=current_end,
                            chunk_index=chunk_index,
                            total_chunks=0,
                        )
                    )
                    chunk_index += 1

            if current_end >= total_duration:
                break
            current_start = current_end - self.overlap

        for chunk in chunks:
            chunk.total_chunks = len(chunks)
        return chunks

    def _chunk_by_estimation(self, transcript_text: str) -> list[TranscriptChunk]:
        words = (transcript_text or "").split()
        if not words:
            return []

        words_per_minute = 150.0
        total_duration = (len(words) / words_per_minute) * 60.0
        if total_duration <= self.chunk_duration:
            return [
                TranscriptChunk(
                    text=transcript_text,
                    start_time=0.0,
                    end_time=total_duration,
                    chunk_index=0,
                    total_chunks=1,
                )
            ]

        chunks: list[TranscriptChunk] = []
        words_per_chunk = int((self.chunk_duration / 60.0) * words_per_minute)
        overlap_words = int((self.overlap / 60.0) * words_per_minute)
        current_start_word = 0
        chunk_index = 0

        while current_start_word < len(words):
            current_end_word = min(current_start_word + words_per_chunk, len(words))
            chunk_words = words[current_start_word:current_end_word]
            chunk_text = " ".join(chunk_words)
            if len(chunk_text) >= self.min_chunk_chars:
                start_time = (current_start_word / words_per_minute) * 60.0
                end_time = (current_end_word / words_per_minute) * 60.0
                chunks.append(
                    TranscriptChunk(
                        text=chunk_text,
                        start_time=start_time,
                        end_time=end_time,
                        chunk_index=chunk_index,
                        total_chunks=0,
                    )
                )
                chunk_index += 1

            if current_end_word >= len(words):
                break
            current_start_word = max(0, current_end_word - overlap_words)

        for chunk in chunks:
            chunk.total_chunks = len(chunks)
        return chunks


class TranscriptSummarizer:
    """Multi-pass summarizer: per-chunk summaries → final merge."""

    def __init__(
        self,
        complete: CompleteFn,
        *,
        chunk_duration_minutes: float = 10.0,
        overlap_minutes: float = 1.0,
        max_summary_tokens: int = 500,
    ):
        self.complete = complete
        self.chunker = TranscriptChunker(
            chunk_duration_minutes=chunk_duration_minutes,
            overlap_minutes=overlap_minutes,
        )
        self.max_summary_tokens = max_summary_tokens

    def summarize_transcript(
        self,
        transcript_text: str,
        transcript_segments: list[dict] | None = None,
        video_title: str = "",
        focus: str = "",
    ) -> dict[str, Any]:
        chunks = self.chunker.chunk_transcript(transcript_text, transcript_segments)
        if not chunks:
            return {
                "ok": False,
                "error": "No chunks created from transcript",
                "summary": "",
                "chunk_summaries": [],
                "num_chunks": 0,
            }

        log.info(
            "Smart-summarizing transcript: %d chars → %d chunks",
            len(transcript_text or ""),
            len(chunks),
        )

        if len(chunks) == 1:
            summary = self._summarize_single(chunks[0].text, video_title, focus)
            return {
                "ok": True,
                "summary": summary,
                "chunk_summaries": [summary],
                "num_chunks": 1,
                "method": "single_pass",
            }

        chunk_summaries: list[str] = []
        for chunk in chunks:
            try:
                summary = self._summarize_chunk(chunk, video_title, focus)
                chunk_summaries.append(summary)
            except Exception as exc:  # noqa: BLE001
                log.warning("Chunk %d summary failed: %s", chunk.chunk_index, exc)
                chunk_summaries.append(f"[Summary unavailable for {chunk.time_range_str}]")

        final = self._combine_summaries(chunk_summaries, video_title, focus)
        return {
            "ok": True,
            "summary": final,
            "chunk_summaries": chunk_summaries,
            "num_chunks": len(chunks),
            "method": "multi_pass",
            "chunk_details": [
                {
                    "index": c.chunk_index,
                    "time_range": c.time_range_str,
                    "char_count": len(c.text),
                }
                for c in chunks
            ],
        }

    def _summarize_single(self, text: str, video_title: str, focus: str) -> str:
        title_ctx = f" from the video '{video_title}'" if video_title else ""
        focus_ctx = f"\n\nFocus especially on: {focus}" if focus else ""
        prompt = (
            f"Please provide a comprehensive summary of this transcript{title_ctx}."
            f"{focus_ctx}\n\n"
            "Include the main topics discussed, key points, important details, "
            "and any conclusions or takeaways.\n\n"
            f"Transcript:\n{text}"
        )
        return self._ask(prompt, self.max_summary_tokens)

    def _summarize_chunk(self, chunk: TranscriptChunk, video_title: str, focus: str) -> str:
        title_ctx = f" from '{video_title}'" if video_title else ""
        focus_ctx = f" Focus on: {focus}." if focus else ""
        prompt = (
            f"Summarize this section ({chunk.time_range_str}) of a video transcript{title_ctx}."
            f"{focus_ctx}\n\n"
            f"This is chunk {chunk.chunk_index + 1} of {chunk.total_chunks}. "
            "Capture the key points discussed in this section.\n\n"
            f"Transcript section:\n{chunk.text}"
        )
        return self._ask(prompt, min(300, self.max_summary_tokens))

    def _combine_summaries(
        self,
        chunk_summaries: list[str],
        video_title: str,
        focus: str,
    ) -> str:
        title_ctx = f" of '{video_title}'" if video_title else ""
        focus_ctx = f"\n\nPay special attention to: {focus}" if focus else ""
        numbered = "\n\n".join(
            f"Section {i + 1}:\n{s}" for i, s in enumerate(chunk_summaries)
        )
        prompt = (
            f"Below are summaries of different sections of a video transcript{title_ctx}. "
            "Please combine them into one coherent, comprehensive summary that covers "
            "the entire video. Maintain chronological flow and avoid repetition."
            f"{focus_ctx}\n\n"
            f"Section summaries:\n{numbered}\n\n"
            "Provide a well-structured final summary:"
        )
        return self._ask(prompt, self.max_summary_tokens)

    def _ask(self, prompt: str, max_tokens: int) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that creates clear, comprehensive "
                    "summaries of video transcripts. Be concise but thorough."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        text = (self.complete(messages, max_tokens) or "").strip()
        return text or "[Empty summary]"


def default_llm_complete(messages: list[dict[str, str]], max_tokens: int) -> str:
    """Complete via Maya's configured LLMClient (no tools / no personality wrap)."""
    from llm import LLMClient

    resp = LLMClient().complete(messages, max_tokens=max_tokens)
    return (resp.content or "").strip()


def smart_summarize_transcript(
    transcript_text: str,
    *,
    transcript_segments: list[dict] | None = None,
    video_title: str = "",
    focus: str = "",
    complete: Optional[CompleteFn] = None,
    chunk_duration_minutes: float = 10.0,
    overlap_minutes: float = 1.0,
    max_summary_tokens: int = 500,
    min_chars_for_chunking: int = 5000,
) -> dict[str, Any]:
    """Run smart summarization when the transcript is long enough; else single-pass."""
    text = (transcript_text or "").strip()
    if not text:
        return {"ok": False, "error": "Empty transcript", "summary": "", "num_chunks": 0}

    fn = complete or default_llm_complete
    # Short transcripts: one LLM pass without chunking overhead
    if len(text) < min_chars_for_chunking and not transcript_segments:
        summarizer = TranscriptSummarizer(
            fn,
            chunk_duration_minutes=chunk_duration_minutes,
            overlap_minutes=overlap_minutes,
            max_summary_tokens=max_summary_tokens,
        )
        summary = summarizer._summarize_single(text, video_title, focus)
        return {
            "ok": True,
            "summary": summary,
            "chunk_summaries": [summary],
            "num_chunks": 1,
            "method": "single_pass",
        }

    summarizer = TranscriptSummarizer(
        fn,
        chunk_duration_minutes=chunk_duration_minutes,
        overlap_minutes=overlap_minutes,
        max_summary_tokens=max_summary_tokens,
    )
    return summarizer.summarize_transcript(
        text,
        transcript_segments=transcript_segments,
        video_title=video_title,
        focus=focus,
    )
