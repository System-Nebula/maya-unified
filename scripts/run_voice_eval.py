"""Run the voice-facts regression suite against ds4-flash and write a report.

Usage:
    steam-run .venv/bin/python scripts/run_voice_eval.py

Exits non-zero if any case fails a hard invariant (wrong/no tool, deflection
phrase, or runner error), so it can gate CI.
"""

from __future__ import annotations

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


def main() -> int:
    _load_dotenv()
    from services.paths import setup_paths

    setup_paths()  # put voicepipe + voice-runtime on sys.path (as conftest does)
    from services.eval.runner import EvalRunner, write_report
    from services.eval.suite import load_suite

    model = os.getenv("EVAL_LLM_MODEL", DEFAULT_MODEL)
    suite = load_suite(SUITE)
    runner = EvalRunner(suite)
    if not runner.api_key:
        print(f"ERROR: no API key — set {suite.api_key_env} (env or .env)", file=sys.stderr)
        return 2

    advisory_ids = {c.id for c in suite.cases if c.advisory}
    report = runner.run(models=[model])
    json_path, md_path = write_report(report, REPORT_DIR)

    print(f"\n# {report.suite} — {model}\n")
    matrix = report.matrix()
    gating_failed = 0
    advisory_failed = 0
    for case_id in sorted(matrix):
        cell = matrix[case_id].get(model, "—")
        is_advisory = case_id in advisory_ids
        passed = cell.startswith("PASS")
        if not passed:
            if is_advisory:
                advisory_failed += 1
            else:
                gating_failed += 1
        tag = "  [advisory]" if is_advisory else ""
        print(f"  {case_id:32s} {cell}{tag}")
    print(f"\nreport: {md_path}")
    gating_total = len(matrix) - len(advisory_ids)
    print(f"gating: {gating_total - gating_failed}/{gating_total} passed", end="")
    if advisory_failed:
        print(f"  (+{advisory_failed} advisory failing — tracked, non-blocking)", end="")
    print()
    return 1 if gating_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
