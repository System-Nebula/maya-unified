"""Post-imagine LLM remark: witty caption with optional vision context."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Callable

try:
    from observability import get_logger, span
except ImportError:  # pragma: no cover
    import logging
    from contextlib import contextmanager

    get_logger = logging.getLogger

    @contextmanager
    def span(*_args, **_kwargs):
        yield None


log = get_logger("maya-unified.imagine.remark")

_REMARK_GUIDE = (
    "The user asked you to generate an image. You are reacting to the result you just "
    "delivered. Reply with ONE short witty spoken line about the image — dry humor, "
    "playful roast, or poetic shade (e.g. \"here's more pictures of stupid dogs\", "
    "\"that sunset you'll never see\"). Stay in Maya's voice. No URLs, job IDs, or "
    "meta commentary about tools or generation. One or two sentences max."
)

_IMAGINE_OUTPUT_PREFIX = "/imagine-outputs"
_IMAGINE_REMARK_FALLBACK = "Image ready."


def imagine_image_root() -> Path:
    return Path(os.environ.get("MAYA_IMAGE_ROOT", "data/outputs/maya-image")).resolve()


def remark_enabled(settings: dict[str, Any] | None = None) -> bool:
    env = os.getenv("MAYA_IMAGINE_REMARK", "").strip().lower()
    if env in {"0", "false", "no", "off"}:
        return False
    if env in {"1", "true", "yes", "on"}:
        return True
    from services.imagine.settings import get_imagine_settings

    imagine = get_imagine_settings(settings)
    return bool(imagine.get("remark_enabled", True))


def remark_vision_model(settings: dict[str, Any] | None = None) -> str:
    """Explicit vision model from Settings → Imagine (blank = text-only remarks)."""
    from services.imagine.settings import get_imagine_settings

    imagine = get_imagine_settings(settings)
    return str(imagine.get("remark_vision_model") or "").strip()


def resolve_imagine_output_path(url: str) -> Path | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        from urllib.parse import urlparse

        parsed = urlparse(raw)
        raw = parsed.path or ""
    prefix = _IMAGINE_OUTPUT_PREFIX.rstrip("/")
    if raw.startswith(prefix + "/"):
        rel = raw[len(prefix) + 1 :]
    elif raw.startswith(prefix):
        rel = raw[len(prefix) :].lstrip("/")
    else:
        return None
    path = (imagine_image_root() / rel).resolve()
    root = imagine_image_root()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def load_image_for_llm(url: str) -> dict[str, Any] | None:
    path = resolve_imagine_output_path(url)
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        log.warning("imagine_remark_image_read_failed path=%s error=%s", path, exc)
        return None
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{encoded}"},
    }


def _vision_available(settings: dict[str, Any] | None = None) -> bool:
    """Vision remarks require an explicit vision-capable model in settings."""
    from services.llm.provider import is_webllm_provider

    if is_webllm_provider():
        return False
    return bool(remark_vision_model(settings))


def build_remark_messages(
    *,
    prompt: str,
    artifact: dict[str, Any],
    system_prompt: str,
    settings: dict[str, Any] | None = None,
    use_vision: bool | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return (messages, vision_used)."""
    model_label = str(artifact.get("model") or artifact.get("model_key") or "local model")
    workflow = str(artifact.get("workflow_name") or artifact.get("workflow_id") or "")
    meta_bits = [f"Prompt: {prompt.strip()}", f"Model: {model_label}"]
    if workflow:
        meta_bits.append(f"Workflow: {workflow}")
    if artifact.get("gen_ms") is not None:
        meta_bits.append(f"Generation time: {int(artifact['gen_ms'])} ms")

    want_vision = use_vision if use_vision is not None else _vision_available(settings)
    image_part = None
    if want_vision:
        image_part = load_image_for_llm(str(artifact.get("url") or ""))
    vision_used = image_part is not None

    user_text = (
        "\n".join(meta_bits)
        + "\n\nLook at the generated image and "
        + ("react wittily to what you see." if vision_used else "react wittily to what was generated from the prompt.")
    )
    if vision_used and image_part is not None:
        user_content: str | list[dict[str, Any]] = [
            {"type": "text", "text": user_text},
            image_part,
        ]
    else:
        user_content = user_text

    system = f"{system_prompt.strip()}\n\n{_REMARK_GUIDE}".strip()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ], vision_used


def parse_imagine_tool_result(result: str) -> dict[str, Any] | None:
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("ok"):
        return None
    if not str(data.get("url") or "").strip():
        return None
    return data


def artifact_from_tool_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "image",
        "url": data.get("url"),
        "job_id": data.get("job_id"),
        "model": data.get("model"),
        "model_key": data.get("model_key"),
        "workflow_id": data.get("workflow_id"),
        "workflow_name": data.get("workflow_name"),
        "gen_ms": data.get("gen_ms"),
        "prompt": data.get("prompt"),
    }


def _emit_remark_tool_phase(
    emit: Callable[..., None] | None,
    *,
    phase: str,
    vision_model: str = "",
    result: str = "",
) -> None:
    if emit is None:
        return
    try:
        if phase == "start":
            args = {"vision_model": vision_model} if vision_model else {}
            emit(type="tool_start", tool="imagine_remark", args=args)
        elif phase == "done":
            emit(type="tool_end", tool="imagine_remark", result=result[:200] if result else "")
    except Exception:  # noqa: BLE001
        pass


def _remark_failure_context(settings: dict[str, Any] | None, vision_model: str) -> dict[str, str]:
    try:
        from services.llm.provider import get_provider_name
    except ImportError:  # pragma: no cover
        return {"provider": "", "vision_model": vision_model}
    return {
        "provider": get_provider_name(),
        "vision_model": vision_model or remark_vision_model(settings),
    }


def emit_imagine_artifact(data: dict[str, Any], emit: Callable[..., None] | None) -> dict[str, Any]:
    """Broadcast image artifact + footer meta on enriched chat SSE."""
    artifact = artifact_from_tool_result(data)
    if emit is not None:
        emit(
            type="ai",
            text="",
            artifacts=[artifact],
            job_id=data.get("job_id"),
            model=data.get("model"),
            model_key=data.get("model_key"),
            workflow_id=data.get("workflow_id"),
            workflow_name=data.get("workflow_name"),
            gen_ms=data.get("gen_ms"),
        )
    return artifact


def stream_remark_text(
    llm: Any,
    messages: list[dict[str, Any]],
    *,
    emit: Callable[..., None] | None = None,
    vision_model: str = "",
) -> str:
    """Stream remark tokens; optional emit receives partial ai events."""
    from agent import finalize_reply_text

    model = str(vision_model or "").strip() or None
    parts: list[str] = []
    stream = llm.stream_messages(messages, model=model)
    for chunk in stream:
        if not chunk:
            continue
        parts.append(str(chunk))
        if emit is not None:
            emit(type="ai", text=str(chunk))
    raw = "".join(parts).strip()
    remark, cue = finalize_reply_text(raw)
    if cue and emit is not None:
        emit(type="delivery", cue=cue)
    return remark


def _stream_remark_safe(
    llm: Any,
    *,
    prompt: str,
    artifact: dict[str, Any],
    system_prompt: str,
    settings: dict[str, Any] | None,
    emit: Callable[..., None] | None,
    force_text_only: bool = False,
) -> str:
    """Stream remark with vision attempt and text-only fallback; never raises."""
    use_vision = False if force_text_only else None
    remark_messages, vision_used = build_remark_messages(
        prompt=prompt,
        artifact=artifact,
        system_prompt=system_prompt,
        settings=settings,
        use_vision=use_vision,
    )
    vision_model = remark_vision_model(settings) if vision_used else ""

    _emit_remark_tool_phase(emit, phase="start", vision_model=vision_model)
    try:
        remark = stream_remark_text(
            llm,
            remark_messages,
            emit=emit,
            vision_model=vision_model,
        )
        if remark:
            _emit_remark_tool_phase(emit, phase="done", result=remark)
            return remark
    except Exception as exc:  # noqa: BLE001
        ctx = _remark_failure_context(settings, vision_model)
        log.warning(
            "imagine_remark_stream_failed vision=%s provider=%s vision_model=%s error=%s",
            vision_used,
            ctx["provider"],
            ctx["vision_model"],
            exc,
        )
        _emit_remark_tool_phase(emit, phase="done", result=str(exc)[:200])

    if force_text_only or not vision_used:
        return ""

    try:
        text_messages, _ = build_remark_messages(
            prompt=prompt,
            artifact=artifact,
            system_prompt=system_prompt,
            settings=settings,
            use_vision=False,
        )
        _emit_remark_tool_phase(emit, phase="start")
        remark = stream_remark_text(llm, text_messages, emit=emit, vision_model="")
        if remark:
            _emit_remark_tool_phase(emit, phase="done", result=remark)
        return remark
    except Exception as exc:  # noqa: BLE001
        ctx = _remark_failure_context(settings, "")
        log.warning(
            "imagine_remark_text_only_failed provider=%s error=%s",
            ctx["provider"],
            exc,
        )
        _emit_remark_tool_phase(emit, phase="done", result=str(exc)[:200])
        return ""


def finish_imagine_tool_remark(
    llm: Any,
    messages: list[dict],
    tool_result: str,
    *,
    system_prompt: str,
    settings: dict[str, Any] | None = None,
    emit: Callable[..., None] | None = None,
    force_text_only: bool = False,
    emit_artifact: bool = True,
) -> str | None:
    """After imagine_generate, stream a witty remark (vision opt-in). Never raises."""
    data = parse_imagine_tool_result(tool_result)
    if data is None:
        return None
    if emit_artifact:
        emit_imagine_artifact(data, emit)
    prompt = str(data.get("prompt") or "")
    artifact = artifact_from_tool_result(data)
    with span(
        "imagine.remark",
        vision_enabled=not force_text_only and _vision_available(settings),
        image_job_id=str(data.get("job_id") or ""),
        image_model_key=str(data.get("model_key") or ""),
    ):
        remark = _stream_remark_safe(
            llm,
            prompt=prompt,
            artifact=artifact,
            system_prompt=system_prompt,
            settings=settings,
            emit=emit,
            force_text_only=force_text_only,
        )
        return remark or None


def finish_imagine_remark_with_fallback(
    llm: Any,
    messages: list[dict],
    tool_result: str,
    *,
    system_prompt: str,
    settings: dict[str, Any] | None = None,
    emit: Callable[..., None] | None = None,
) -> str:
    """Always return spoken text after a successful imagine job; never raises."""
    if not remark_enabled(settings):
        return _IMAGINE_REMARK_FALLBACK

    remark = finish_imagine_tool_remark(
        llm,
        messages,
        tool_result,
        system_prompt=system_prompt,
        settings=settings,
        emit=emit,
    )
    if remark:
        return remark

    remark = finish_imagine_tool_remark(
        llm,
        messages,
        tool_result,
        system_prompt=system_prompt,
        settings=settings,
        emit=emit,
        force_text_only=True,
        emit_artifact=False,
    )
    return remark or _IMAGINE_REMARK_FALLBACK
