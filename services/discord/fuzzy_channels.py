"""Fuzzy Discord voice-channel matching for STT / LLM name errors."""

from __future__ import annotations

import difflib
import re
from typing import Any

_WORD_SWAPS = (
    (r"\bfor\b", "4"),
    (r"\bfour\b", "4"),
    (r"\bto\b", "2"),
    (r"\btwo\b", "2"),
    (r"\bmiles\b", "myles"),
    (r"\bmile\b", "myles"),
    (r"\btoo\b", "2"),
)


def norm_name(value: str) -> str:
    s = (value or "").strip().lstrip("#").lower()
    s = re.sub(r"[\s_-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", norm_name(value))


def hint_variants(hint: str) -> list[str]:
    """Generate spelling variants for homophones and common STT mistakes."""
    raw = (hint or "").strip()
    if not raw:
        return []
    base = norm_name(raw)
    variants = [raw, base]
    current = [base]
    for pattern, repl in _WORD_SWAPS:
        next_round: list[str] = []
        for v in current:
            next_round.append(v)
            changed = re.sub(pattern, repl, v)
            if changed != v:
                next_round.append(changed)
        current = list(dict.fromkeys(next_round))
    variants.extend(current)
    return list(dict.fromkeys(v for v in variants if v))


def _token_overlap_match(hint: str, channels: list[Any]) -> Any | None:
    hint_tokens = set(norm_name(hint).split())
    if len(hint_tokens) < 2:
        return None
    best = None
    best_score = 0.0
    for channel in channels:
        ctokens = set(norm_name(channel.name).split())
        if len(ctokens) < 2:
            continue
        inter = hint_tokens & ctokens
        if len(inter) < 2:
            continue
        score = len(inter) / len(hint_tokens | ctokens)
        if score > best_score:
            best_score = score
            best = channel
    if best_score >= 0.45:
        return best
    return None


def resolve_voice_channel_fuzzy(guild: Any, channel_name: str, aliases: dict[str, str] | None = None) -> Any | None:
    """Resolve a voice channel when exact / substring match fails."""
    hint = (channel_name or "").strip().lstrip("#")
    if not hint:
        return None

    channels = list(getattr(guild, "voice_channels", []) or [])
    if not channels:
        return None

    if aliases:
        alias = aliases.get(hint) or aliases.get(norm_name(hint))
        if alias:
            hint = alias

    for variant in hint_variants(hint):
        target = norm_name(variant)
        target_key = norm_name_key(variant)
        exact = [
            c
            for c in channels
            if norm_name(c.name) == target or norm_name_key(c.name) == target_key
        ]
        if exact:
            return exact[0]
        partial = [
            c
            for c in channels
            if target in norm_name(c.name) or target_key in norm_name_key(c.name)
        ]
        if len(partial) == 1:
            return partial[0]

    token_match = _token_overlap_match(hint, channels)
    if token_match is not None:
        return token_match

    names = [c.name for c in channels]
    for variant in hint_variants(hint):
        close = difflib.get_close_matches(variant, names, n=1, cutoff=0.55)
        if close:
            return next(c for c in channels if c.name == close[0])

    hint_key = norm_name_key(hint)
    keyed = [(c, norm_name_key(c.name)) for c in channels]
    close_keys = difflib.get_close_matches(hint_key, [k for _, k in keyed], n=1, cutoff=0.72)
    if close_keys:
        return next(c for c, k in keyed if k == close_keys[0])

    return None
