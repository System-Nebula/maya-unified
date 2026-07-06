#!/usr/bin/env python3
"""Run LLM tool-call eval suites against OpenRouter models."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.eval.runner import run_suite, write_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM tool-call eval suite")
    parser.add_argument(
        "--suite",
        required=True,
        help="Path to YAML suite (e.g. tests/fixtures/eval/tool_suites/voice-tools.yaml)",
    )
    parser.add_argument(
        "--models",
        default=None,
        help="Comma-separated model slugs (overrides suite models list)",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        default=None,
        help="Run only these case ids (repeatable)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Directory for report.json and summary.md",
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else None

    try:
        report = run_suite(args.suite, models=models, case_ids=args.cases)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    matrix = report.matrix()
    models_ordered = sorted({r.model for r in report.results})
    print(f"Suite: {report.suite}")
    for case_id, row in sorted(matrix.items()):
        for model in models_ordered:
            cell = row.get(model, "—")
            print(f"  {case_id:24}  {model:45}  {cell}")

    if args.out:
        json_path, md_path = write_report(report, args.out)
        print(f"\nWrote {json_path}")
        print(f"Wrote {md_path}")

    failed = sum(1 for r in report.results if not r.score.passed or r.error)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
