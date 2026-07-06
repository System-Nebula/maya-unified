"""Load and validate YAML eval suites."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EvalCase:
    id: str
    user: str
    transcript: list[dict[str, str]] = field(default_factory=list)
    expect: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalSuite:
    suite: str
    models: list[str]
    cases: list[EvalCase]
    api_key_env: str = "OPENROUTER_API_KEY"
    tool_mode: str = "auto"
    max_rounds: int = 3
    max_tokens: int | None = None


def _require(obj: dict[str, Any], key: str) -> Any:
    if key not in obj:
        raise ValueError(f"missing required field '{key}'")
    return obj[key]


def _parse_case(raw: dict[str, Any]) -> EvalCase:
    case_id = str(_require(raw, "id"))
    user = str(_require(raw, "user"))
    transcript = raw.get("transcript") or []
    if not isinstance(transcript, list):
        raise ValueError(f"case {case_id}: transcript must be a list")
    for turn in transcript:
        if not isinstance(turn, dict) or "role" not in turn or "content" not in turn:
            raise ValueError(f"case {case_id}: transcript entries need role and content")
    expect = raw.get("expect") or {}
    if not isinstance(expect, dict):
        raise ValueError(f"case {case_id}: expect must be a mapping")
    return EvalCase(id=case_id, user=user, transcript=list(transcript), expect=expect)


def load_suite(path: str | Path) -> EvalSuite:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{p}: suite root must be a mapping")

    suite_name = str(_require(data, "suite"))
    models = _require(data, "models")
    if not isinstance(models, list) or not models:
        raise ValueError(f"{p}: models must be a non-empty list")
    models = [str(m) for m in models]

    raw_cases = _require(data, "cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError(f"{p}: cases must be a non-empty list")
    cases = [_parse_case(c) for c in raw_cases]

    tool_mode = str(data.get("tool_mode") or "auto").lower()
    if tool_mode not in ("auto", "native", "json"):
        raise ValueError(f"{p}: tool_mode must be auto, native, or json")

    max_rounds = int(data.get("max_rounds") or 3)
    max_tokens = data.get("max_tokens")
    if max_tokens is not None:
        max_tokens = int(max_tokens)

    return EvalSuite(
        suite=suite_name,
        models=models,
        cases=cases,
        api_key_env=str(data.get("api_key_env") or "OPENROUTER_API_KEY"),
        tool_mode=tool_mode,
        max_rounds=max(1, max_rounds),
        max_tokens=max_tokens,
    )
