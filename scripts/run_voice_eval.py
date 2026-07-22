"""Run the voice-facts regression suite against ds4-flash and write a report.

Usage:
    steam-run .venv/bin/python scripts/run_voice_eval.py
    steam-run .venv/bin/python scripts/run_voice_eval.py --frameworks native,dspy,ax

With multiple frameworks this becomes the Ax-vs-DSPy A/B: every case runs under
each routing framework against the same model, and a per-framework pass rate is
printed so you can decide whether to adopt Ax or keep DSPy.

Exits non-zero if any case fails a hard invariant (wrong/no tool, deflection
phrase, or runner error) under the FIRST framework, so the default single-
framework run still gates CI unchanged.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_MODEL = "openrouter/deepseek/deepseek-v4-flash"
SUITE = ROOT / "tests" / "fixtures" / "eval" / "tool_suites" / "voice-facts.yaml"
REPORT_DIR = ROOT / "reports" / "voice-facts"


def _load_dotenv() -> None:
    """Load KEY=VALUE from the repo .env so OPENROUTER_API_KEY is available."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _column(model: str, framework: str) -> str:
    """Mirror RunResult.column: plain model for native, model::framework otherwise."""
    return model if framework == "native" else f"{model}::{framework}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the voice-facts suite / Ax-vs-DSPy A/B.")
    parser.add_argument(
        "--frameworks",
        default="native",
        help="Comma-separated routing frameworks to run: native, dspy, ax (default: native).",
    )
    parser.add_argument("--model", default=os.getenv("EVAL_LLM_MODEL", DEFAULT_MODEL))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    frameworks = [f.strip() for f in args.frameworks.split(",") if f.strip()] or ["native"]
    model = args.model

    _load_dotenv()
    from services.paths import setup_paths

    setup_paths()  # put voicepipe + voice-runtime on sys.path (as conftest does)
    from services.eval.runner import EvalRunner, write_report
    from services.eval.suite import load_suite

    suite = load_suite(SUITE)
    runner = EvalRunner(suite)
    if not runner.api_key:
        print(f"ERROR: no API key — set {suite.api_key_env} (env or .env)", file=sys.stderr)
        return 2

    advisory_ids = {c.id for c in suite.cases if c.advisory}
    report = runner.run(models=[model], frameworks=frameworks)
    json_path, md_path = write_report(report, REPORT_DIR)
    matrix = report.matrix()

    print(f"\n# {report.suite} — {model}\n")
    gating_total = len(matrix) - len(advisory_ids)
    summary: dict[str, tuple[int, int]] = {}  # framework -> (gating_pass, advisory_fail)

    for framework in frameworks:
        col = _column(model, framework)
        print(f"## framework: {framework}")
        gating_failed = 0
        advisory_failed = 0
        for case_id in sorted(matrix):
            cell = matrix[case_id].get(col, "—")
            is_advisory = case_id in advisory_ids
            if not cell.startswith("PASS"):
                if is_advisory:
                    advisory_failed += 1
                else:
                    gating_failed += 1
            tag = "  [advisory]" if is_advisory else ""
            print(f"  {case_id:32s} {cell}{tag}")
        summary[framework] = (gating_total - gating_failed, advisory_failed)
        print()

    print(f"report: {md_path}\n")
    print("A/B summary (gating pass rate):")
    for framework in frameworks:
        gating_pass, advisory_failed = summary[framework]
        extra = f"  (+{advisory_failed} advisory failing)" if advisory_failed else ""
        print(f"  {framework:8s} {gating_pass}/{gating_total} passed{extra}")

    # Gate on the first framework only, preserving the default CI contract.
    primary_pass, _ = summary[frameworks[0]]
    return 1 if primary_pass < gating_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
