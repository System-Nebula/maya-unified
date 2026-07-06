"""Score ToolLoop results against suite expectations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScoreResult:
    passed: bool
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _trace_tools(trace: list[dict]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for entry in trace:
        name = entry.get("tool") or ""
        args = entry.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        out.append((str(name), args))
    return out


def _match_arg(value: Any, predicate: Any) -> bool:
    if not isinstance(predicate, dict):
        return value == predicate
    if "eq" in predicate:
        return value == predicate["eq"]
    text = str(value or "")
    if "contains" in predicate:
        needle = str(predicate["contains"])
        return needle.lower() in text.lower()
    if "regex" in predicate:
        return bool(re.search(str(predicate["regex"]), text, re.I))
    return False


def _check_tools(expected: list[dict], trace: list[dict]) -> tuple[list[str], list[str]]:
    checks: list[str] = []
    failures: list[str] = []
    actual = _trace_tools(trace)

    if len(actual) < len(expected):
        failures.append(
            f"expected {len(expected)} tool call(s), got {len(actual)}: "
            f"{[n for n, _ in actual] or '(none)'}"
        )
        return checks, failures

    for idx, exp in enumerate(expected):
        exp_name = str(exp.get("name") or "")
        act_name, act_args = actual[idx]
        label = f"tools[{idx}]"
        if act_name != exp_name:
            failures.append(f"{label}: expected tool '{exp_name}', got '{act_name}'")
            continue
        checks.append(f"{label}: tool '{exp_name}' called")
        exp_args = exp.get("args") or {}
        if isinstance(exp_args, dict):
            for field_name, pred in exp_args.items():
                if _match_arg(act_args.get(field_name), pred):
                    checks.append(f"{label}: arg '{field_name}' matched")
                else:
                    failures.append(
                        f"{label}: arg '{field_name}' expected {pred!r}, got {act_args.get(field_name)!r}"
                    )
    return checks, failures


def _check_final_text(expect: dict[str, Any], final_text: str) -> tuple[list[str], list[str]]:
    checks: list[str] = []
    failures: list[str] = []
    text = (final_text or "").strip()
    if "not_empty" in expect and expect["not_empty"]:
        if text:
            checks.append("final_text: not empty")
        else:
            failures.append("final_text: expected non-empty response")
    if "contains" in expect:
        needle = str(expect["contains"])
        if needle.lower() in text.lower():
            checks.append(f"final_text: contains {needle!r}")
        else:
            failures.append(f"final_text: expected to contain {needle!r}")
    if "regex" in expect:
        pat = str(expect["regex"])
        if re.search(pat, text, re.I):
            checks.append(f"final_text: matches /{pat}/")
        else:
            failures.append(f"final_text: expected to match /{pat}/")
    return checks, failures


def score_case(
    expect: dict[str, Any],
    *,
    trace: list[dict],
    final_text: str,
    rounds: int,
    protocol: str | None = None,
) -> ScoreResult:
    checks: list[str] = []
    failures: list[str] = []

    if "tools" in expect:
        c, f = _check_tools(expect["tools"], trace)
        checks.extend(c)
        failures.extend(f)

    forbid = expect.get("forbid_tools") or []
    if isinstance(forbid, list):
        called = {name for name, _ in _trace_tools(trace)}
        for name in forbid:
            if name in called:
                failures.append(f"forbid_tools: '{name}' was called")
            else:
                checks.append(f"forbid_tools: '{name}' not called")

    if "max_rounds" in expect:
        limit = int(expect["max_rounds"])
        if rounds <= limit:
            checks.append(f"max_rounds: {rounds} <= {limit}")
        else:
            failures.append(f"max_rounds: {rounds} exceeded limit {limit}")

    if "final_text" in expect:
        ft_expect = expect["final_text"]
        if isinstance(ft_expect, dict):
            c, f = _check_final_text(ft_expect, final_text)
            checks.extend(c)
            failures.extend(f)

    if "protocol" in expect:
        expected_proto = str(expect["protocol"]).lower()
        actual_proto = (protocol or "unknown").lower()
        if actual_proto == expected_proto:
            checks.append(f"protocol: {actual_proto}")
        else:
            failures.append(f"protocol: expected '{expected_proto}', got '{actual_proto}'")

    return ScoreResult(passed=not failures, checks=checks, failures=failures)
