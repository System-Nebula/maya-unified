"""LLM connection health checks for the reasoning profile."""

from __future__ import annotations

import time
from typing import Any

from services.settings.catalog import fetch_openai_models
from services.settings.store import apply_to_config

PROBE_MAX_TOKENS = 8
SLOW_LATENCY_MS = 8000
HEALTH_CACHE_TTL_S = 90.0

_health_cache: dict[str, tuple[float, dict[str, Any]]] = {}

try:
    from observability import record_llm_probe, span
except ImportError:
    from contextlib import contextmanager
    from typing import Iterator

    @contextmanager
    def span(name: str, **attributes: Any) -> Iterator[Any]:
        yield None

    def record_llm_probe(*args: Any, **kwargs: Any) -> None:
        pass


def _resolved_model(reasoning: dict[str, Any]) -> str:
    provider = str(reasoning.get("provider", "lm_studio")).lower()
    if provider == "litellm":
        litellm_cfg = reasoning.get("litellm") or {}
        return str(litellm_cfg.get("model") or reasoning.get("model", ""))
    if provider == "webllm":
        webllm = reasoning.get("webllm") or {}
        return str(webllm.get("model_id") or "")
    return str(reasoning.get("model", ""))


def _supports_models_list(reasoning: dict[str, Any]) -> bool:
    provider = str(reasoning.get("provider", "lm_studio")).lower()
    base_url = str(reasoning.get("base_url", "")).strip()
    if not base_url:
        return False
    if provider == "lm_studio":
        return True
    if provider == "litellm":
        litellm_cfg = reasoning.get("litellm") or {}
        return str(litellm_cfg.get("mode", "sdk")) == "proxy"
    return False


def _span_event(sp: Any, name: str) -> None:
    if sp is not None and hasattr(sp, "add_event"):
        try:
            sp.add_event(name)
        except Exception:  # noqa: BLE001
            pass


def _set_span_attrs(sp: Any, **attrs: Any) -> None:
    if sp is None:
        return
    for key, val in attrs.items():
        if val is None:
            continue
        try:
            sp.set_attribute(key, val)
        except Exception:  # noqa: BLE001
            pass


def llm_ready_from_health(result: dict[str, Any]) -> bool:
    """True when the reasoning LLM profile is usable for text chat."""
    return str(result.get("status", "")).lower() in ("ok", "warn")


def build_agent_capabilities(voice_ready: bool, health: dict[str, Any]) -> dict[str, bool]:
    """Capability matrix for progressive UI disclosure."""
    llm_ready = llm_ready_from_health(health)
    return {
        "text_chat": llm_ready,
        "text_chat_enriched": voice_ready and llm_ready,
        "voice_session": voice_ready,
        "tts_preview": voice_ready,
        "eq_live": voice_ready,
        "tools": voice_ready,
    }


def _health_cache_key(reasoning: dict[str, Any]) -> str:
    provider = str(reasoning.get("provider", ""))
    litellm = reasoning.get("litellm") or {}
    return "|".join(
        [
            provider,
            str(reasoning.get("base_url", "")),
            str(reasoning.get("model", "")),
            str(litellm.get("mode", "")),
            str(litellm.get("model", "")),
        ]
    )


def get_cached_llm_health(
    reasoning: dict[str, Any],
    *,
    run_probe: bool | None = None,
) -> dict[str, Any]:
    """Health for status polls — models-only when possible, cached probe otherwise."""
    key = _health_cache_key(reasoning)
    now = time.monotonic()
    cached = _health_cache.get(key)
    if cached and (now - cached[0]) < HEALTH_CACHE_TTL_S:
        return dict(cached[1])

    if run_probe is None:
        run_probe = not _supports_models_list(reasoning)

    result = check_llm_health(reasoning, run_probe=run_probe)
    if llm_ready_from_health(result):
        _health_cache[key] = (now, dict(result))
    return result


def invalidate_llm_health_cache() -> None:
    _health_cache.clear()


def check_llm_health(reasoning: dict[str, Any], *, run_probe: bool = True) -> dict[str, Any]:
    """Validate the reasoning LLM profile via /models listing and a tiny completion."""
    provider = str(reasoning.get("provider", "lm_studio")).lower()
    model = _resolved_model(reasoning)
    result: dict[str, Any] = {
        "status": "error",
        "provider": provider,
        "model": model,
        "latency_ms": None,
        "models_found": 0,
        "detail": "",
    }

    if provider == "webllm":
        result.update(
            status="skipped",
            detail="WebLLM runs in the browser — validate on the Conversation page.",
        )
        return result

    models_found = 0
    models_ok = False
    models_degraded = False

    if _supports_models_list(reasoning):
        started = time.monotonic()
        with span(
            "llm.provider.models_check",
            **{"llm.provider": provider, "llm.model": model},
        ) as sp:
            _span_event(sp, "models_check.started")
            models = fetch_openai_models(
                str(reasoning.get("base_url", "")),
                str(reasoning.get("api_key", "")),
                timeout=3.0,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            models_found = len(models)
            models_ok = models_found > 0
            _set_span_attrs(
                sp,
                **{
                    "http.route": "/models",
                    "llm.models.count": models_found,
                    "duration_ms": duration_ms,
                },
            )
            _span_event(sp, "models_check.succeeded" if models_ok else "models_check.failed")
            record_llm_probe(
                duration_ms,
                status="ok" if models_ok else "warn",
                provider=provider,
                model=model,
                phase="models_check",
            )
        if not models_ok:
            models_degraded = True

    if not run_probe:
        if _supports_models_list(reasoning):
            result.update(
                status="ok" if models_ok else "warn",
                models_found=models_found,
                detail=(
                    "Model listing OK"
                    if models_ok
                    else "Could not list models — run Test connection for full probe."
                ),
            )
        else:
            result.update(
                status="warn",
                models_found=0,
                detail="LLM not verified yet — run Test connection in Settings → Reasoning.",
            )
        return result

    apply_to_config({"reasoning": reasoning})
    from services.llm.provider import create_llm_client

    probe_status = "error"
    detail = ""
    latency_ms = 0
    error_type: str | None = None

    started = time.monotonic()
    try:
        with span(
            "llm.connection_test",
            **{
                "llm.provider": provider,
                "llm.model": model,
                "test.message": True,
                "request.type": "quiet",
                "stream": False,
                "max_tokens": PROBE_MAX_TOKENS,
            },
        ) as sp:
            _span_event(sp, "test.started")
            client = create_llm_client()
            resp = client.complete(
                [{"role": "user", "content": "Hi"}],
                max_tokens=PROBE_MAX_TOKENS,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            content = getattr(resp, "content", "") or ""
            if not content.strip():
                probe_status = "warn"
                detail = "Probe returned empty content"
            elif latency_ms > SLOW_LATENCY_MS:
                probe_status = "warn"
                detail = f"Probe succeeded but slow ({latency_ms} ms)"
            else:
                probe_status = "ok"
                detail = f"Probe OK ({latency_ms} ms)"
            _set_span_attrs(sp, duration_ms=latency_ms)
            _span_event(sp, "test.succeeded")
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - started) * 1000)
        probe_status = "error"
        detail = str(exc)[:200]
        error_type = type(exc).__name__
        with span(
            "llm.connection_test",
            **{
                "llm.provider": provider,
                "llm.model": model,
                "duration_ms": latency_ms,
            },
        ) as sp:
            if sp is not None and hasattr(sp, "record_exception"):
                try:
                    sp.record_exception(exc)
                except Exception:  # noqa: BLE001
                    pass
            _span_event(sp, "test.failed")

    record_llm_probe(
        latency_ms,
        status=probe_status,
        provider=provider,
        model=model,
        phase="test_message",
        error_type=error_type,
    )

    if probe_status == "error":
        final_status = "error"
    elif probe_status == "warn" or models_degraded:
        final_status = "warn"
        if models_degraded and probe_status == "ok":
            detail = f"Probe OK ({latency_ms} ms) but model listing unavailable"
    else:
        final_status = "ok"

    result.update(
        status=final_status,
        latency_ms=latency_ms,
        models_found=models_found,
        detail=detail,
    )
    return result
