"""Server-side imagine fallback when the LLM skips imagine_generate."""

from __future__ import annotations

import json
from typing import Any, Callable

try:
    from observability import get_logger
except ImportError:  # pragma: no cover
    import logging

    get_logger = logging.getLogger

from services.imagine.intent import extract_imagine_prompt, parse_imagine_model_from_text
from services.imagine.remark import (
    _IMAGINE_REMARK_FALLBACK,
    finish_imagine_remark_with_fallback,
    remark_enabled,
)

log = get_logger("maya-unified.imagine.fallback")


def trace_has_imagine_success(trace: list[dict]) -> bool:
    """True if tool loop already completed imagine_generate successfully."""
    from services.imagine.remark import parse_imagine_tool_result

    for entry in trace:
        if entry.get("tool") != "imagine_generate":
            continue
        if parse_imagine_tool_result(str(entry.get("result") or "")):
            return True
    return False


def run_imagine_nl_fallback(
    *,
    user_text: str,
    operator_id: str | None,
    corr_id: str,
    messages: list[dict],
    llm: Any,
    emit: Callable[..., None] | None,
    settings: dict[str, Any] | None,
) -> tuple[str, bool]:
    """Run imagine_generate directly when NL intent was detected but the LLM skipped the tool.

    Returns (reply_text, streamed_via_emit).
    """
    prompt = extract_imagine_prompt(user_text)
    model = parse_imagine_model_from_text(user_text)
    if not prompt:
        return "I couldn't figure out what to draw from that.", False

    from tools.imagine import _imagine_generate_handler

    log.info(
        "imagine_nl_fallback corr_id=%s prompt=%r model=%s",
        corr_id,
        prompt[:120],
        model or "",
    )
    handler_args: dict[str, Any] = {
        "prompt": prompt,
        "operator_id": operator_id,
        "corr_id": corr_id,
    }
    if model:
        handler_args["model"] = model

    try:
        result = _imagine_generate_handler(handler_args)
    except Exception as exc:  # noqa: BLE001
        log.warning("imagine_nl_fallback_failed: %s", exc)
        return f"I couldn't generate that image: {exc}", False

    if not result.get("ok"):
        err = str(result.get("error") or "generation failed").strip()
        return f"I couldn't generate that image: {err}", False

    result_json = json.dumps(result, ensure_ascii=False)
    if remark_enabled(settings):
        system = llm.base_system_prompt()
        try:
            remark = finish_imagine_remark_with_fallback(
                llm,
                messages,
                result_json,
                system_prompt=system,
                settings=settings,
                emit=emit,
            )
            return remark, True
        except Exception as exc:  # noqa: BLE001
            log.warning("imagine_nl_fallback_remark_failed: %s", exc)
            return _IMAGINE_REMARK_FALLBACK, bool(emit)

    from services.imagine.remark import emit_imagine_artifact

    emit_imagine_artifact(result, emit)
    return _IMAGINE_REMARK_FALLBACK, bool(emit)
