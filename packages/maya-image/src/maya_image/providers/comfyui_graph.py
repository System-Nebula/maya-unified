"""Generic ComfyUI graph runner — inject bindings and POST to comfyui-api /prompt.

Runs any ComfyUI API-format graph stored in ``image_workflows.comfy_graph`` against the
local comfyui-api (:3030). The bare wrapper's ``/prompt`` is synchronous and returns base64
images, so completions are captured on submit, persisted to the image-output store, and
returned through the standard ``BaseImageProvider`` poll contract.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog
from opentelemetry import trace

from maya_image.comfy_assets import (
    MissingComfyAssetError,
    ensure_assets,
    missing_assets,
    required_assets_for_graph,
)
from maya_image.comfy_bind import inject_request
from maya_image.storage import ImageStorage
from maya_image.workflows import get_workflow
from maya_image.types.image_job import ImageJobInput, ImageJobOutput, ImageJobStatus, ImageMode, ImageOutput

logger = structlog.get_logger()
_tracer = trace.get_tracer("image.comfyui.graph")


_OOM_RE = re.compile(r"out\s*of\s*memory|OutOfMemoryError|CUDA out of memory", re.I)
_VLLM_PROCESS_RE = re.compile(r"vllm", re.I)
_GENERIC_OUTPUT_FAIL = "Failed to get prompt outputs"
VRAM_HEAVY_MODEL_KEYS = frozenset({"krea2-turbo"})
ComfyProgressCallback = Callable[[str, str], Awaitable[None]]


def _walk_json(obj: Any, out: list[Any]) -> None:
    if isinstance(obj, dict):
        out.append(obj)
        for value in obj.values():
            _walk_json(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json(item, out)


def _extract_execution_error(body: str) -> dict[str, str | None]:
    """Best-effort parse of Comfy ``execution_error`` / node failure payloads."""
    details: dict[str, str | None] = {
        "error_type": None,
        "node_id": None,
        "node_type": None,
        "exception_message": None,
    }
    blobs: list[Any] = []
    try:
        _walk_json(json.loads(body), blobs)
    except Exception:
        blobs = []

    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        for key in ("execution_error", "error"):
            nested = blob.get(key)
            if not isinstance(nested, dict):
                continue
            details["error_type"] = details["error_type"] or str(
                nested.get("exception_type") or nested.get("type") or ""
            ) or None
            details["node_id"] = details["node_id"] or str(nested.get("node_id") or "") or None
            details["node_type"] = details["node_type"] or str(
                nested.get("node_type") or nested.get("class_type") or ""
            ) or None
            msg = nested.get("exception_message") or nested.get("message")
            if msg:
                details["exception_message"] = str(msg)[:400]

        node_errors = blob.get("node_errors")
        if isinstance(node_errors, dict):
            for node_id, node_err in node_errors.items():
                if not isinstance(node_err, dict):
                    continue
                details["node_id"] = details["node_id"] or str(node_id)
                for err in node_err.get("errors") or []:
                    if not isinstance(err, dict):
                        continue
                    details["error_type"] = details["error_type"] or str(
                        err.get("type") or err.get("exception_type") or ""
                    ) or None
                    msg = err.get("message") or err.get("details")
                    if msg:
                        details["exception_message"] = str(msg)[:400]

    if _OOM_RE.search(body):
        details["error_type"] = details["error_type"] or "torch.OutOfMemoryError"
    return details


def _is_oom_error(body: str, details: dict[str, str | None], *, workflow_name: str = "") -> bool:
    haystack = " ".join(
        filter(
            None,
            [
                body,
                details.get("error_type") or "",
                details.get("exception_message") or "",
                workflow_name,
            ],
        )
    )
    if _OOM_RE.search(haystack):
        return True
    if _GENERIC_OUTPUT_FAIL in body and "krea2" in workflow_name.lower():
        return True
    return False


def _oom_user_message(*, workflow_name: str = "", vllm_hint: bool = False) -> str:
    label = workflow_name or "sampling"
    msg = (
        f"GPU out of memory during {label} (KSampler). "
        "Restart comfyui-api or free VRAM (~18 GB required for Krea2)."
    )
    if vllm_hint:
        msg += " vLLM is holding GPU memory; stop Ornith/vLLM first."
    return msg


def _vllm_contention_message(
    *, vram_free_mb: int, vllm_used_mb: int, vllm_pid: int | None
) -> str:
    return (
        "Krea2 is waiting for GPU memory. Ornith/vLLM is using this GPU right now, "
        "so I stopped before submitting to avoid another ComfyUI OOM. "
        "Pause Ornith/vLLM and retry /imagine."
    )


def _parse_gpu_process_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 3:
        return None
    try:
        pid = int(parts[0])
        used_mib = int(parts[-1])
        name = ", ".join(parts[1:-1]) if len(parts) > 3 else parts[1]
        return {"pid": pid, "name": name, "used_mib": used_mib}
    except ValueError:
        return None


def _detect_vllm_contention(
    processes: list[dict[str, Any]],
) -> tuple[bool, int, int | None]:
    for proc in processes:
        if _VLLM_PROCESS_RE.search(str(proc.get("name", ""))):
            return True, int(proc.get("used_mib", 0)), proc.get("pid")
    return False, 0, None


async def _query_gpu_processes() -> list[dict[str, Any]]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0 or not stdout.strip():
            return []
        out: list[dict[str, Any]] = []
        for line in stdout.decode().splitlines():
            parsed = _parse_gpu_process_line(line)
            if parsed:
                out.append(parsed)
        return out
    except Exception:
        return []


def _is_html_error_body(body: str) -> bool:
    head = (body or "").lstrip()[:240].lower()
    return head.startswith("<!doctype") or "<html" in head or "_next/static" in head


def _truncate_summary(text: str, limit: int = 200) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


_MODEL_MOUNT_MISMATCH_MSG = (
    "ComfyUI cannot see local model files. Weights may exist on the host but the "
    "container mount likely targets the wrong path (/app/ComfyUI vs /opt/ComfyUI). "
    "See infra/comfyui/README.md."
)
_KREA2_VERSION_MSG = (
    "Krea 2 is not supported by this ComfyUI build (needs 0.26+). "
    "Rebuild comfyui-api per infra/comfyui/README.md."
)


def _extract_node_errors(body: str, data: dict[str, Any]) -> dict[str, Any] | None:
    node_errors = data.get("node_errors")
    if node_errors:
        return node_errors if isinstance(node_errors, dict) else None
    message = str(data.get("message", ""))
    start = message.find("{")
    if start == -1:
        return None
    try:
        nested = json.loads(message[start:])
    except Exception:
        return None
    nested_errors = nested.get("node_errors")
    return nested_errors if isinstance(nested_errors, dict) else None


def _is_model_mount_mismatch(node_errors: dict[str, Any] | None) -> bool:
    if not node_errors:
        return False
    loader_types = {"VAELoader", "UNETLoader", "CLIPLoader"}
    for node_err in node_errors.values():
        if not isinstance(node_err, dict):
            continue
        if node_err.get("class_type") not in loader_types:
            continue
        for err in node_err.get("errors") or []:
            if not isinstance(err, dict) or err.get("type") != "value_not_in_list":
                continue
            details = str(err.get("details") or "")
            extra = err.get("extra_info") or {}
            received = str(extra.get("received_value") or "")
            if "not in []" in details:
                return True
            if (
                node_err.get("class_type") == "VAELoader"
                and received.endswith(".safetensors")
                and "pixel_space" in details
            ):
                return True
    return False


def _is_krea2_type_unsupported(node_errors: dict[str, Any] | None) -> bool:
    if not node_errors:
        return False
    for node_err in node_errors.values():
        if not isinstance(node_err, dict):
            continue
        if node_err.get("class_type") != "CLIPLoader":
            continue
        for err in node_err.get("errors") or []:
            if not isinstance(err, dict) or err.get("type") != "value_not_in_list":
                continue
            details = str(err.get("details") or "")
            if "krea2" in details and "type:" in details:
                return True
    return False


def _summarize_comfy_error(
    body: str,
    *,
    workflow_name: str = "",
    vllm_hint: bool = False,
    status_code: int | None = None,
) -> str:
    """Pull node-level detail out of a comfyui-api error body when present.

    comfyui-api wraps the real ComfyUI failure as a stringified JSON inside ``message``
    (e.g. ``"Failed to queue prompt: {... node_errors ...}"``), so dig into that.
    """
    if _is_html_error_body(body):
        code = status_code if status_code is not None else "?"
        api_url = os.getenv("COMFYUI_API_URL", "http://127.0.0.1:3000").rstrip("/")
        return _truncate_summary(
            f"COMFYUI_API_URL ({api_url}) returned HTML {code} — "
            "is comfyui-api running? (curl $COMFYUI_API_URL/docs should not be a web app 404 page)"
        )

    details = _extract_execution_error(body)
    if _is_oom_error(body, details, workflow_name=workflow_name):
        return _oom_user_message(workflow_name=workflow_name, vllm_hint=vllm_hint)

    try:
        data = json.loads(body)
    except Exception:
        return _truncate_summary(body)
    node_errors = _extract_node_errors(body, data)
    if node_errors and _is_krea2_type_unsupported(node_errors):
        return _truncate_summary(_KREA2_VERSION_MSG)
    if node_errors and _is_model_mount_mismatch(node_errors):
        return _truncate_summary(_MODEL_MOUNT_MISMATCH_MSG)
    if not node_errors:
        message = str(data.get("message", ""))
        if _GENERIC_OUTPUT_FAIL in message and "krea2" in workflow_name.lower():
            return _oom_user_message(workflow_name=workflow_name, vllm_hint=vllm_hint)
        return _truncate_summary(message or json.dumps(data))
    return _truncate_summary(json.dumps(node_errors))


def _summarize_comfy_unreachable(*, workflow_name: str = "", cause: Exception | None = None) -> str:
    api_url = os.getenv("COMFYUI_API_URL", "http://127.0.0.1:3000").rstrip("/")
    cause_text = f" ({cause})" if cause else ""
    return _truncate_summary(
        f"cannot connect to COMFYUI_API_URL ({api_url}) — "
        f"is comfyui-api running?{cause_text} "
        "(curl $COMFYUI_API_URL/docs should not be a web app 404 page)"
    )


def _set_comfy_error_span_attrs(span: trace.Span, body: str) -> dict[str, str | None]:
    details = _extract_execution_error(body)
    for key, value in details.items():
        if value:
            span.set_attribute(f"comfyui.{key}", value[:200])
    return details


COMFYUI_API_URL = os.getenv("COMFYUI_API_URL", "http://127.0.0.1:3000").rstrip("/")
COMFYUI_NATIVE_URL = os.getenv("COMFYUI_NATIVE_URL", "http://127.0.0.1:8188").rstrip("/")
COMFYUI_API_KEY = os.getenv("COMFYUI_API_KEY", "")
KREA2_MIN_VRAM_FREE_BYTES = int(os.getenv("COMFYUI_KREA2_MIN_VRAM_FREE", str(2 * 1024**3)))
KREA2_REQUIRED_VRAM_BYTES = int(os.getenv("COMFYUI_KREA2_REQUIRED_VRAM", str(18 * 1024**3)))
COMFYUI_GRAPH_CONNECT_TIMEOUT_SEC = float(os.getenv("COMFYUI_GRAPH_CONNECT_TIMEOUT_SEC", "5"))
COMFYUI_GRAPH_SUBMIT_TIMEOUT_SEC = float(os.getenv("COMFYUI_GRAPH_SUBMIT_TIMEOUT_SEC", "90"))
COMFYUI_ZIMAGE_SUBMIT_TIMEOUT_SEC = float(os.getenv("COMFYUI_ZIMAGE_SUBMIT_TIMEOUT_SEC", "180"))
COMFYUI_GRAPH_KREA2_SUBMIT_TIMEOUT_SEC = float(
    os.getenv("COMFYUI_GRAPH_KREA2_SUBMIT_TIMEOUT_SEC", "120")
)
MAYA_ARENA_SUBMIT_TIMEOUT_SEC = float(os.getenv("MAYA_ARENA_SUBMIT_TIMEOUT_SEC", "120"))
COMFYUI_GRAPH_HISTORY_TIMEOUT_SEC = float(os.getenv("COMFYUI_GRAPH_HISTORY_TIMEOUT_SEC", "30"))
_OUTPUT_URL_PREFIX = os.getenv("MAYA_IMAGE_URL_PREFIX", "/imagine-outputs")


def _submit_timeout_sec(workflow, request: ImageJobInput | None = None) -> float:
    if request is not None and (
        request.mode == ImageMode.ARENA or request.metadata.get("arena_slot")
    ):
        return MAYA_ARENA_SUBMIT_TIMEOUT_SEC
    model_key = str((getattr(workflow, "params", None) or {}).get("model_key") or "")
    workflow_name = str(getattr(workflow, "name", "")).lower()
    workflow_id = str(getattr(workflow, "id", "")).lower()
    if (
        workflow_id == "z-image-turbo-t2i"
        or "z-image" in workflow_name
        or model_key == "z-image-turbo"
    ):
        return COMFYUI_ZIMAGE_SUBMIT_TIMEOUT_SEC
    if model_key in VRAM_HEAVY_MODEL_KEYS or "krea2" in workflow_name:
        return COMFYUI_GRAPH_KREA2_SUBMIT_TIMEOUT_SEC
    if model_key in {"flux2", "ideogram/4.0"} or "flux2" in workflow_name or "ideogram" in workflow_name:
        return COMFYUI_GRAPH_KREA2_SUBMIT_TIMEOUT_SEC
    return COMFYUI_GRAPH_SUBMIT_TIMEOUT_SEC


def _httpx_timeouts(*, read_sec: float) -> httpx.Timeout:
    return httpx.Timeout(
        connect=COMFYUI_GRAPH_CONNECT_TIMEOUT_SEC,
        read=read_sec,
        write=30.0,
        pool=5.0,
    )


def _comfy_timeout_message(*, stage: str, timeout_sec: float, workflow_name: str = "") -> str:
    label = workflow_name or "ComfyUI"
    return (
        f"{label} did not finish within {int(timeout_sec)}s during {stage}. "
        "Try again or increase COMFYUI_GRAPH_SUBMIT_TIMEOUT_SEC for cold starts."
    )


class ComfyUIGraphProvider:
    """Run any ComfyUI API-format graph from image_workflows.comfy_graph."""

    provider_key = "comfyui:graph"
    model_key = "ideogram/4.0-local"

    def __init__(self, *, storage: ImageStorage | None = None):
        self._storage = storage or ImageStorage()
        self._results: dict[str, ImageJobOutput] = {}
        self._workflows_by_prompt: dict[str, Any] = {}
        self._last_vram_contention: dict[str, Any] = {}
        self._progress_cb: ComfyProgressCallback | None = None

    def bind_progress_callback(self, callback: ComfyProgressCallback | None) -> None:
        self._progress_cb = callback

    def clear_progress_callback(self) -> None:
        self._progress_cb = None

    async def _emit_stage(
        self,
        stage: str,
        message: str,
        span: trace.Span | None = None,
        *,
        elapsed_ms: int | None = None,
    ) -> None:
        active = span if span is not None else trace.get_current_span()
        active.set_attribute("comfyui.stage", stage)
        if elapsed_ms is not None:
            active.set_attribute("comfyui.elapsed_ms", elapsed_ms)
        try:
            from observability.boundary import emit_visibility

            emit_visibility(
                "comfyui.stage",
                span=active,
                boundary="comfyui.graph",
                stage=stage,
                message=message,
                elapsed_ms=elapsed_ms,
            )
        except ImportError:
            logger.info(
                "comfyui.stage",
                stage=stage,
                message=message,
                elapsed_ms=elapsed_ms,
            )
        cb = self._progress_cb
        if cb is None:
            return
        try:
            await cb(stage, message)
        except Exception as exc:
            logger.warning("comfyui.progress_callback_failed", stage=stage, error=str(exc))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if COMFYUI_API_KEY:
            headers["Authorization"] = f"Bearer {COMFYUI_API_KEY}"
        return headers

    def _load_workflow(self, request: ImageJobInput):
        workflow_id = request.metadata.get("workflow_id")
        if not workflow_id:
            raise ValueError("comfyui:graph requires workflow_id in metadata")
        return get_workflow(workflow_id)

    def _build_graph(self, workflow, request: ImageJobInput) -> dict[str, Any]:
        bindings = list((workflow.ui_schema or {}).get("bindings") or [])
        return inject_request(workflow.comfy_graph, bindings, request, params=workflow.params)

    async def _ensure_assets(
        self,
        graph: dict[str, Any],
        *,
        check_only: bool = False,
    ) -> list[str]:
        """Off-thread asset preflight (downloads + docker cp are blocking I/O)."""
        needed = required_assets_for_graph(graph)
        if not needed:
            return []
        if check_only:
            return await asyncio.to_thread(missing_assets, needed)
        return await asyncio.to_thread(ensure_assets, needed)

    @staticmethod
    def _workflow_model_label(workflow) -> str:
        params = workflow.params or {}
        return str(workflow.display_name or params.get("model_key") or workflow.name)

    def _store_images(self, images: list[Any], workflow=None) -> ImageJobOutput:
        outputs: list[ImageOutput] = []
        for img in images:
            data: bytes | None = None
            if isinstance(img, str):
                raw = img.split(",", 1)[1] if img.startswith("data:") else img
                try:
                    data = base64.b64decode(raw)
                except Exception:
                    outputs.append(ImageOutput(url=img, mime_type="image/png"))
                    continue
            elif isinstance(img, dict):
                b64 = img.get("data") or img.get("base64")
                if b64:
                    data = base64.b64decode(b64)
                elif img.get("url"):
                    outputs.append(
                        ImageOutput(url=img["url"], mime_type=img.get("content_type", "image/png"))
                    )
                    continue
            if data is None:
                continue
            local_path = self._storage.write_bytes(
                data, filename=f"{uuid.uuid4().hex}.png", subdir="outputs"
            )
            rel = Path(local_path).relative_to(self._storage.root)
            outputs.append(
                ImageOutput(
                    url=f"{_OUTPUT_URL_PREFIX}/{rel}", local_path=local_path, mime_type="image/png"
                )
            )
        model_label = self._workflow_model_label(workflow) if workflow is not None else self.model_key
        return ImageJobOutput(provider=self.provider_key, model=model_label, outputs=outputs)

    @staticmethod
    def _extract_images(data: dict[str, Any]) -> list[Any]:
        images = data.get("images") or []
        if not images and isinstance(data.get("outputs"), dict):
            for node_out in data["outputs"].values():
                if isinstance(node_out, dict) and node_out.get("images"):
                    images = node_out["images"]
                    break
        return images

    @staticmethod
    def _needs_vram_preflight(workflow) -> bool:
        model_key = str((workflow.params or {}).get("model_key") or "")
        return model_key in VRAM_HEAVY_MODEL_KEYS or "krea2" in workflow.name.lower()

    async def _query_vram_stats(self, client: httpx.AsyncClient) -> dict[str, Any]:
        try:
            resp = await client.get(f"{COMFYUI_NATIVE_URL}/system_stats", timeout=5.0)
            if resp.status_code == 200:
                device = resp.json()["devices"][0]
                return {
                    "vram_free": int(device["vram_free"]),
                    "vram_total": int(device["vram_total"]),
                    "source": "comfy_native",
                }
        except Exception:
            pass
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=memory.free,memory.total",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout.strip():
                free_mib, total_mib = (int(x.strip()) for x in stdout.decode().split(",", 1))
                mib = 1024 * 1024
                return {
                    "vram_free": free_mib * mib,
                    "vram_total": total_mib * mib,
                    "source": "nvidia-smi",
                }
        except Exception:
            pass
        return {"vram_free": None, "vram_total": None, "source": "unknown"}

    async def _free_comfy_vram(self, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.post(
                f"{COMFYUI_NATIVE_URL}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def _vram_preflight(
        self,
        client: httpx.AsyncClient,
        workflow,
        span: trace.Span,
        payload: dict[str, Any],
    ) -> None:
        stats = await self._query_vram_stats(client)
        vram_free = stats.get("vram_free")
        vram_total = stats.get("vram_total")
        processes = await _query_gpu_processes()
        vllm_found, vllm_used_mib, vllm_pid = _detect_vllm_contention(processes)
        self._last_vram_contention = {
            "vllm_detected": vllm_found,
            "vllm_used_mb": vllm_used_mib,
            "vllm_pid": vllm_pid,
        }
        if vram_free is not None:
            free_mb = vram_free // (1024 * 1024)
            total_mb = (vram_total // (1024 * 1024)) if vram_total else None
            logger.info(
                "comfyui.vram_preflight",
                workflow=workflow.name,
                vram_free_mb=free_mb,
                vram_total_mb=total_mb,
                source=stats.get("source"),
                vllm_detected=vllm_found,
                vllm_used_mb=vllm_used_mib if vllm_found else None,
            )
            span.set_attribute("comfyui.vram_free_mb", free_mb)
            if total_mb is not None:
                span.set_attribute("comfyui.vram_total_mb", total_mb)
            if vllm_found:
                span.set_attribute("comfyui.vllm_detected", True)
                span.set_attribute("comfyui.vllm_used_mb", vllm_used_mib)
                if vllm_pid is not None:
                    span.set_attribute("comfyui.vllm_pid", vllm_pid)
            if vram_free < KREA2_REQUIRED_VRAM_BYTES and vllm_found:
                logger.warning(
                    "comfyui.vram_contention",
                    workflow=workflow.name,
                    vram_free_mb=free_mb,
                    vllm_used_mb=vllm_used_mib,
                    vllm_pid=vllm_pid,
                )
                raise RuntimeError(
                    _vllm_contention_message(
                        vram_free_mb=free_mb,
                        vllm_used_mb=vllm_used_mib,
                        vllm_pid=vllm_pid,
                    )
                )
            if vram_free < KREA2_MIN_VRAM_FREE_BYTES:
                freed = await self._free_comfy_vram(client)
                span.set_attribute("comfyui.vram_free_attempted", freed)
                payload["free_memory"] = True
                await asyncio.sleep(1.5)
                stats = await self._query_vram_stats(client)
                retry_free = stats.get("vram_free")
                if retry_free is not None:
                    span.set_attribute("comfyui.vram_free_mb_after", retry_free // (1024 * 1024))

    async def _post_prompt(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        workflow,
        span: trace.Span,
        *,
        retried: bool = False,
        timeout_sec: float | None = None,
    ) -> httpx.Response:
        read_sec = timeout_sec if timeout_sec is not None else _submit_timeout_sec(workflow)
        span.set_attribute("comfyui.submit_timeout_sec", read_sec)
        await self._emit_stage(
            "post_prompt",
            "ComfyUI accepted the request; loading/sampling...",
            span,
        )
        started = time.monotonic()
        try:
            resp = await client.post(
                f"{COMFYUI_API_URL}/prompt", json=payload, headers=self._headers()
            )
        except httpx.TimeoutException as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            span.set_attribute("comfyui.timeout_stage", "post_prompt")
            span.set_attribute("comfyui.elapsed_ms", elapsed_ms)
            try:
                from observability.boundary import emit_visibility

                emit_visibility(
                    "comfyui.timeout",
                    span=span,
                    boundary="comfyui.graph",
                    stage="post_prompt",
                    elapsed_ms=elapsed_ms,
                    timeout_sec=read_sec,
                )
            except ImportError:
                pass
            raise RuntimeError(
                _comfy_timeout_message(
                    stage="post_prompt", timeout_sec=read_sec, workflow_name=workflow.name
                )
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            summary = _summarize_comfy_unreachable(workflow_name=workflow.name, cause=exc)
            raise RuntimeError(
                f"comfyui-api /prompt failed for {workflow.name}: {summary}"
            ) from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        span.set_attribute("comfyui.post_prompt_ms", elapsed_ms)
        if resp.status_code >= 400:
            _set_comfy_error_span_attrs(span, resp.text)
            if (
                not retried
                and resp.status_code >= 500
                and self._needs_vram_preflight(workflow)
                and _GENERIC_OUTPUT_FAIL in resp.text
            ):
                freed = await self._free_comfy_vram(client)
                span.set_attribute("comfyui.vram_free_retry", freed)
                if freed:
                    payload = dict(payload)
                    payload["free_memory"] = True
                    await asyncio.sleep(2.0)
                    return await self._post_prompt(
                        client, payload, workflow, span, retried=True, timeout_sec=read_sec
                    )
        return resp

    async def submit(self, request: ImageJobInput) -> tuple[str, ImageJobStatus]:
        workflow = self._load_workflow(request)
        self._last_vram_contention = {}
        submit_started = time.monotonic()
        with _tracer.start_as_current_span("comfyui.graph.submit") as span:
            span.set_attribute("image.workflow_id", workflow.id)
            span.set_attribute("image.workflow_name", workflow.name)
            if request.metadata.get("corr_id"):
                span.set_attribute("chat.corr_id", str(request.metadata["corr_id"]))
            if request.metadata.get("model_key"):
                span.set_attribute("image.model_key", str(request.metadata["model_key"]))
            await self._emit_stage(
                "submit",
                "Checking GPU and workflow...",
                span,
            )
            if not workflow.comfy_graph:
                if workflow.params.get("workflow_endpoint"):
                    from maya_image.providers.comfyui_ideogram import ComfyUIIdeogramProvider

                    return await ComfyUIIdeogramProvider().submit(request)
                raise ValueError(f"workflow {workflow.name} has no comfy_graph")

            graph = self._build_graph(workflow, request)

            assets_started = time.monotonic()
            check_only = request.mode == ImageMode.ARENA or bool(request.metadata.get("arena_slot"))
            with _tracer.start_as_current_span("comfyui.graph.ensure_assets"):
                missing = await self._ensure_assets(graph, check_only=check_only)
            if missing:
                span.set_attribute("comfyui.missing_assets", ",".join(missing))
                raise MissingComfyAssetError(missing, model=workflow.name)
            await self._emit_stage(
                "ensure_assets",
                "Checking GPU and workflow...",
                span,
                elapsed_ms=int((time.monotonic() - assets_started) * 1000),
            )

            payload: dict[str, Any] = {"prompt": graph}
            webhook_url = request.metadata.get("webhook_url")
            if webhook_url:
                payload["webhook_v2"] = webhook_url

            read_sec = _submit_timeout_sec(workflow, request)
            async with httpx.AsyncClient(timeout=_httpx_timeouts(read_sec=read_sec)) as client:
                if self._needs_vram_preflight(workflow):
                    preflight_started = time.monotonic()
                    await self._vram_preflight(client, workflow, span, payload)
                    await self._emit_stage(
                        "vram_preflight",
                        "Checking GPU and workflow...",
                        span,
                        elapsed_ms=int((time.monotonic() - preflight_started) * 1000),
                    )
                resp = await self._post_prompt(
                    client, payload, workflow, span, timeout_sec=read_sec
                )
                if resp.status_code >= 400:
                    vllm_hint = bool(self._last_vram_contention.get("vllm_detected"))
                    summary = _summarize_comfy_error(
                        resp.text,
                        workflow_name=workflow.name,
                        vllm_hint=vllm_hint,
                        status_code=resp.status_code,
                    )
                    logger.error(
                        "comfyui_graph_submit_failed",
                        status=resp.status_code,
                        body=resp.text[:500],
                        workflow=workflow.name,
                        error_summary=summary,
                    )
                    span.set_attribute("comfyui.http_status", resp.status_code)
                    raise RuntimeError(
                        f"comfyui-api /prompt failed for {workflow.name}: "
                        f"{resp.status_code} {summary}"
                    )
                data = resp.json()

            await self._emit_stage("decode_store", "Finalizing image...", span)
            images = self._extract_images(data)
            if images:
                span.set_attribute("comfyui.image_count", len(images))
                span.set_attribute(
                    "comfyui.submit_total_ms",
                    int((time.monotonic() - submit_started) * 1000),
                )
                job_id = f"comfyui-graph-{uuid.uuid4().hex}"
                self._results[job_id] = self._store_images(images, workflow)
                span.set_attribute("comfyui.prompt_id", job_id)
                return job_id, ImageJobStatus.COMPLETED
            provider_job_id = data.get("prompt_id") or data.get("id")
            if not provider_job_id:
                raise RuntimeError(
                    f"comfyui-api returned no images and no prompt_id for {workflow.name}"
                )
            span.set_attribute("comfyui.prompt_id", str(provider_job_id))
            self._workflows_by_prompt[str(provider_job_id)] = workflow
            return str(provider_job_id), ImageJobStatus.PROCESSING

    async def poll(
        self, provider_job_id: str
    ) -> tuple[ImageJobStatus, Optional[ImageJobOutput], Optional[str]]:
        cached = self._results.get(provider_job_id)
        if cached is not None:
            return ImageJobStatus.COMPLETED, cached, None
        try:
            async with httpx.AsyncClient(
                timeout=_httpx_timeouts(read_sec=COMFYUI_GRAPH_HISTORY_TIMEOUT_SEC)
            ) as client:
                resp = await client.get(
                    f"{COMFYUI_API_URL}/history/{provider_job_id}", headers=self._headers()
                )
        except httpx.TimeoutException:
            return (
                ImageJobStatus.FAILED,
                None,
                _comfy_timeout_message(stage="history_poll", timeout_sec=COMFYUI_GRAPH_HISTORY_TIMEOUT_SEC),
            )
        if resp.status_code == 404:
            return ImageJobStatus.PROCESSING, None, None
        if resp.status_code >= 400:
            return ImageJobStatus.FAILED, None, resp.text[:300]
        data = resp.json()
        images = self._extract_images(data)
        if images:
            workflow = self._workflows_by_prompt.get(provider_job_id)
            return ImageJobStatus.COMPLETED, self._store_images(images, workflow), None
        if str(data.get("status", "")).lower() in {"failed", "error"}:
            return ImageJobStatus.FAILED, None, str(data.get("error", "comfyui job failed"))
        return ImageJobStatus.PROCESSING, None, None
