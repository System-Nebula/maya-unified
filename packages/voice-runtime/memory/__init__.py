"""Hermes-inspired layered memory for the voice agent.

Layers:
  - curated:   MEMORY.md + USER.md, frozen into the system prompt at session start.
  - sessions:  SQLite log of every turn with FTS5 keyword search.
  - cognitive: optional semantic store (local embeddings) for meaning-based recall.
  - skills:    procedural notes the agent can read/write.
  - review:    background post-turn extraction that lets the agent adapt over time.

`MemoryManager` orchestrates these, exposes tools, and provides the per-turn
context the agent injects into the LLM.
"""

from .manager import MemoryManager

__all__ = ["MemoryManager"]
