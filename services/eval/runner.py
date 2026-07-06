"""Run eval cases against LiteLLM-backed models via ToolLoop."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from services.eval.registry_fixtures import build_eval_registry
from services.eval.scorers import ScoreResult, score_case
from services.eval.stub_executor import ToolExecutor
from services.eval.suite import EvalCase, EvalSuite, load_suite

_VOICE_RUNTIME = Path(__file__).resolve().parents[2] / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))

from config import LLMConfig  # noqa: E402
from llm import LLMResponse, ToolCall  # noqa: E402
from tools.loop import ToolLoop, ToolLoopResult  # noqa: E402


@dataclass
class RunResult:
    suite: str
    case_id: str
    model: str
    final_text: str
    trace: list[dict]
    rounds: int
    protocol: str
    latency_ms: float
    completion_id: str | None
    score: ScoreResult
    error: str | None = None


@dataclass
class SuiteReport:
    suite: str
    results: list[RunResult] = field(default_factory=list)

    def matrix(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for r in self.results:
            out.setdefault(r.case_id, {})
            status = "PASS" if r.score.passed else "FAIL"
            detail = ""
            if r.error:
                detail = r.error
            elif r.score.failures:
                detail = r.score.failures[0]
            out[r.case_id][r.model] = f"{status}" + (f" — {detail}" if detail else "")
        return out


def resolve_api_key(suite: EvalSuite) -> str:
    key = os.environ.get(suite.api_key_env, "").strip()
    if key:
        return key
    try:
        from services.settings.store import load_effective_settings

        settings = load_effective_settings()
        reasoning = settings.get("reasoning") or {}
        return str(reasoning.get("api_key") or "").strip()
    except Exception:
        return ""


class _ProtocolTracker:
    """Wraps an LLM client and records whether native tool_calls were used."""

    def __init__(self, inner: Any):
        self._inner = inner
        self.protocol: str = "none"
        self.last_completion_id: str | None = None

    def base_system_prompt(self, **kwargs: Any) -> str:
        return self._inner.base_system_prompt(**kwargs)

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        resp = self._inner.complete(messages, tools=tools, model=model, max_tokens=max_tokens)
        self.last_completion_id = getattr(self._inner, "last_completion_id", None)
        if resp.tool_calls:
            self.protocol = "native"
        elif tools and self.protocol == "none":
            # Still in native path but model returned text — may parse as json/text call
            self.protocol = "native"
        return resp

    def stream_reply(self, *args: Any, **kwargs: Any):
        return self._inner.stream_reply(*args, **kwargs)

    def stream_messages(self, *args: Any, **kwargs: Any):
        return self._inner.stream_messages(*args, **kwargs)


def _build_llm(model: str, api_key: str, max_tokens: int | None) -> _ProtocolTracker:
    from services.llm.litellm_adapter import LiteLLMAdapter

    cfg = replace(
        LLMConfig(),
        api_key=api_key,
        model=model,
        max_tokens=max_tokens or 512,
        disable_thinking=True,
        reasoning_effort="none",
    )
    return _ProtocolTracker(LiteLLMAdapter(cfg, litellm_model=model))


def _build_messages(llm: _ProtocolTracker, case: EvalCase) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": llm.base_system_prompt()}]
    for turn in case.transcript:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": case.user})
    return messages


def _infer_protocol(tracker: _ProtocolTracker, result: ToolLoopResult) -> str:
    if tracker.protocol == "native" and result.trace:
        return "native"
    if result.trace and tracker.protocol != "native":
        return "json"
    if result.trace:
        return tracker.protocol if tracker.protocol != "none" else "json"
    return "none"


def run_case(
    suite: EvalSuite,
    case: EvalCase,
    model: str,
    *,
    api_key: str,
) -> RunResult:
    llm = _build_llm(model, api_key, suite.max_tokens)
    registry = build_eval_registry()
    executor = ToolExecutor(registry, timeout=5.0)
    loop = ToolLoop(llm, registry, executor, max_rounds=suite.max_rounds, mode=suite.tool_mode)
    messages = _build_messages(llm, case)

    t0 = time.perf_counter()
    error: str | None = None
    try:
        result = loop.run(messages)
    except Exception as exc:  # noqa: BLE001
        result = ToolLoopResult(final_text="", trace=[], rounds=0)
        error = str(exc)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    protocol = _infer_protocol(llm, result)
    score = score_case(
        case.expect,
        trace=result.trace,
        final_text=result.final_text,
        rounds=result.rounds,
        protocol=protocol,
    )

    return RunResult(
        suite=suite.suite,
        case_id=case.id,
        model=model,
        final_text=result.final_text,
        trace=result.trace,
        rounds=result.rounds,
        protocol=protocol,
        latency_ms=latency_ms,
        completion_id=llm.last_completion_id,
        score=score,
        error=error,
    )


class EvalRunner:
    def __init__(self, suite: EvalSuite, *, api_key: str | None = None):
        self.suite = suite
        self.api_key = api_key if api_key is not None else resolve_api_key(suite)

    def run(
        self,
        *,
        models: list[str] | None = None,
        case_ids: list[str] | None = None,
    ) -> SuiteReport:
        if not self.api_key:
            raise RuntimeError(
                f"No API key: set {self.suite.api_key_env} or reasoning.api_key in settings"
            )
        model_list = models or self.suite.models
        cases = self.suite.cases
        if case_ids:
            wanted = set(case_ids)
            cases = [c for c in cases if c.id in wanted]
            if not cases:
                raise ValueError(f"no cases matched filter: {case_ids}")

        report = SuiteReport(suite=self.suite.suite)
        for case in cases:
            for model in model_list:
                report.results.append(run_case(self.suite, case, model, api_key=self.api_key))
        return report


def run_suite(
    path: str | Path,
    *,
    models: list[str] | None = None,
    case_ids: list[str] | None = None,
    api_key: str | None = None,
) -> SuiteReport:
    suite = load_suite(path)
    return EvalRunner(suite, api_key=api_key).run(models=models, case_ids=case_ids)


def result_to_dict(r: RunResult) -> dict[str, Any]:
    return {
        "suite": r.suite,
        "case_id": r.case_id,
        "model": r.model,
        "final_text": r.final_text,
        "trace": r.trace,
        "rounds": r.rounds,
        "protocol": r.protocol,
        "latency_ms": round(r.latency_ms, 1),
        "completion_id": r.completion_id,
        "passed": r.score.passed,
        "checks": r.score.checks,
        "failures": r.score.failures,
        "error": r.error,
    }


def write_report(report: SuiteReport, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    payload = {
        "suite": report.suite,
        "matrix": report.matrix(),
        "results": [result_to_dict(r) for r in report.results],
    }
    json_path = out / "report.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [f"# Eval report: {report.suite}", ""]
    matrix = report.matrix()
    if matrix:
        models = sorted({r.model for r in report.results})
        lines.append("| case | " + " | ".join(models) + " |")
        lines.append("| --- | " + " | ".join(["---"] * len(models)) + " |")
        for case_id, row in sorted(matrix.items()):
            cells = [row.get(m, "—") for m in models]
            lines.append(f"| {case_id} | " + " | ".join(cells) + " |")
    md_path = out / "summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run_case_with_llm(
    case: EvalCase,
    llm: Any,
    *,
    tool_mode: str = "auto",
    max_rounds: int = 3,
) -> ToolLoopResult:
    """Run a single case with a provided LLM (for unit tests with mocks)."""
    tracker = llm if isinstance(llm, _ProtocolTracker) else _ProtocolTracker(llm)
    registry = build_eval_registry()
    executor = ToolExecutor(registry, timeout=5.0)
    loop = ToolLoop(tracker, registry, executor, max_rounds=max_rounds, mode=tool_mode)
    messages = _build_messages(tracker, case)
    return loop.run(messages)


__all__ = [
    "EvalRunner",
    "RunResult",
    "SuiteReport",
    "run_case_with_llm",
    "run_suite",
    "write_report",
]
