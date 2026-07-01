"""Lightweight safety scan for text entering persistent memory.

Memory entries are injected into the system prompt on later sessions, so a
poisoned entry is a prompt-injection vector. This blocks the obvious patterns and
strips invisible Unicode. It is a guard rail, not a guarantee.
"""

from __future__ import annotations

import re

# Phrases that strongly suggest an injection attempt rather than a real fact.
_INJECTION_PATTERNS = [
    r"ignore (all|any|previous|prior) (instructions|prompts)",
    r"disregard (the|your|all) (system|previous) (prompt|instructions)",
    r"you are now (?!a )",  # "you are now DAN/unrestricted/..."
    r"reveal (your|the) (system )?prompt",
    r"print (your|the) (system )?prompt",
    r"exfiltrate|api[_-]?key|private key|password\s*[:=]",
    r"BEGIN RSA PRIVATE KEY",
]

_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Zero-width / bidi / other invisible characters used to hide instructions.
_INVISIBLE_RE = re.compile(
    "[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060\ufeff]"
)


def sanitize(text: str) -> tuple[bool, str]:
    """Return (ok, cleaned_or_reason).

    ok=False with a reason if the text looks like an injection attempt; otherwise
    ok=True with the text stripped of invisible characters.
    """
    if not text or not text.strip():
        return False, "empty entry"
    if _INJECTION_RE.search(text):
        return False, "blocked: entry matches a prompt-injection pattern"
    cleaned = _INVISIBLE_RE.sub("", text).strip()
    if not cleaned:
        return False, "blocked: entry was only invisible characters"
    return True, cleaned
