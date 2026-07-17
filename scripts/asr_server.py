"""OpenAI-compatible transcription server for Qwen3-ASR (transformers backend).

Works on native Windows without vLLM. Exposes:
  POST /v1/audio/transcriptions
  GET  /health   — always responsive (liveness + queue metrics)
  GET  /readyz   — 503 until model is loaded and warmed (ASR-003)
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME = _ROOT / "packages" / "voice-runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

from asr_lang import normalize_qwen3_asr_language  # noqa: E402
from asr_limits import (  # noqa: E402
    MAX_DURATION_S,
    MAX_UPLOAD_BYTES,
    READ_CHUNK_BYTES,
    AsrMetrics,
    UploadTooLarge,
    audio_duration_s,
    enforce_duration,
    enforce_upload_size,
)

_metrics = AsrMetrics()
_model = None
_infer_lock: asyncio.Semaphore | None = None
_metrics_lock = threading.Lock()

app = FastAPI(title="Qwen3-ASR Windows Server")


def _sem() -> asyncio.Semaphore:
    global _infer_lock
    if _infer_lock is None:
        _infer_lock = asyncio.Semaphore(1)
    return _infer_lock


def load_model(model_id: str) -> None:
    global _model
    from qwen_asr import Qwen3ASRModel

    _metrics.model_id = model_id
    _metrics.ready = False
    _metrics.load_error = None
    _metrics.cuda = torch.cuda.is_available()
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    device_map = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"Loading {_metrics.model_id} on {device_map} ({dtype})...")
    _model = Qwen3ASRModel.from_pretrained(
        _metrics.model_id,
        dtype=dtype,
        device_map=device_map,
        max_new_tokens=256,
    )
    print("ASR model loaded — warming...")
    _warm_model()
    _metrics.ready = True
    print("ASR model ready.")


def _warm_model() -> None:
    """Tiny silence pass so first real request is not a cold start."""
    if _model is None:
        return
    try:
        import numpy as np

        sr = 16000
        samples = np.zeros(sr // 10, dtype=np.float32)
        buf = io.BytesIO()
        sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
        raw = buf.getvalue()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(raw)
            path = tmp.name
        try:
            _model.transcribe(audio=path, language="English", return_time_stamps=False)
        finally:
            Path(path).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        print(f"ASR warm-up skipped: {exc}", file=sys.stderr)


def probe_wav_meta(raw: bytes) -> tuple[int, int]:
    try:
        wav, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid audio: {exc}") from exc
    arr = wav.reshape(-1) if hasattr(wav, "reshape") else wav
    n = int(arr.shape[0]) if hasattr(arr, "shape") else len(arr)
    return n, int(sr)


def _transcribe_sync(raw: bytes, *, language: str | None, filename: str) -> str:
    """Blocking GPU/CPU inference — must not run on the ASGI event loop."""
    if _model is None:
        raise RuntimeError("model not loaded")
    lang = normalize_qwen3_asr_language(language)
    suffix = Path(filename or "speech.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        try:
            results = _model.transcribe(
                audio=tmp_path,
                language=lang,
                return_time_stamps=False,
            )
        except Exception:
            wav, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
            results = _model.transcribe(
                audio=(wav, int(sr)),
                language=lang,
                return_time_stamps=False,
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    text = ""
    if results:
        first = results[0]
        text_val = getattr(first, "text", None)
        if text_val is not None:
            text = str(text_val).strip()
    return text


async def _read_upload_limited(file: UploadFile, *, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    raw = bytearray()
    while True:
        chunk = await file.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        if len(raw) + len(chunk) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"upload too large (>{max_bytes} bytes)",
            )
        raw.extend(chunk)
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    return bytes(raw)


def _http_from_upload_error(exc: UploadTooLarge) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/health")
async def health():
    """Liveness: always answers so probes stay responsive during inference."""
    with _metrics_lock:
        snap = _metrics.snapshot()
    return {"ok": True, **snap}


@app.get("/readyz")
async def readyz():
    """Readiness: 503 until model is loaded and warmed."""
    with _metrics_lock:
        snap = _metrics.snapshot()
    if not _metrics.ready or _model is None:
        return JSONResponse({"ok": False, "ready": False, **snap}, status_code=503)
    return {"ok": True, **snap}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str | None = Form(None),
    language: str | None = Form(None),
):
    del model
    if not _metrics.ready or _model is None:
        return JSONResponse(
            {"error": _metrics.load_error or "model not ready"},
            status_code=503,
        )

    raw = await _read_upload_limited(file)
    try:
        enforce_upload_size(len(raw))
        n_samples, sr = probe_wav_meta(raw)
        enforce_duration(audio_duration_s(n_samples, sr))
    except UploadTooLarge as exc:
        raise _http_from_upload_error(exc) from exc

    with _metrics_lock:
        _metrics.waiting += 1
    try:
        await _sem().acquire()
    finally:
        with _metrics_lock:
            _metrics.waiting = max(0, _metrics.waiting - 1)

    with _metrics_lock:
        _metrics.in_flight += 1
    t0 = time.perf_counter()
    try:
        text = await asyncio.to_thread(
            _transcribe_sync,
            raw,
            language=language,
            filename=file.filename or "speech.wav",
        )
        return {"text": text}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500, f"transcription failed: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        with _metrics_lock:
            _metrics.in_flight = max(0, _metrics.in_flight - 1)
            _metrics.last_inference_ms = round(elapsed_ms, 1)
            _metrics.inference_count += 1
        _sem().release()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("VA_ASR_MODEL", "Qwen/Qwen3-ASR-0.6B"))
    parser.add_argument("--host", default=os.environ.get("VA_ASR_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("VA_ASR_PORT", "8091")),
    )
    args = parser.parse_args()
    if args.port == 8001:
        print(
            "WARNING: port 8001 collides with VTube Studio; prefer VA_ASR_PORT=8091",
            file=sys.stderr,
        )

    try:
        load_model(args.model)
    except Exception as exc:  # noqa: BLE001
        _metrics.load_error = f"{type(exc).__name__}: {exc}"
        _metrics.ready = False
        print(f"ASR model failed to load: {exc}", file=sys.stderr)
        raise

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
