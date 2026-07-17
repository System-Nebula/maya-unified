"""Speech-to-text backends: Qwen3-ASR (HTTP) or faster-whisper (local)."""

from __future__ import annotations

import io
import logging
import os
import tempfile
import time
import wave
from typing import Any, Protocol

import numpy as np

from config import CONFIG, STTConfig
from cuda_compat import resolve_torch_device
from asr_lang import normalize_qwen3_asr_language

log = logging.getLogger("maya-unified.voice.stt")

# Dedicated default ASR port (must not equal VTube Studio's 8001).
DEFAULT_ASR_PORT = 8091
VTS_COLLISION_PORT = 8001

# HTTP statuses safe to retry once (transient). Never retry 4xx invalid-audio.
_TRANSIENT_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504})


class STTBackend(Protocol):
    def transcribe_array(
        self,
        audio_int16: np.ndarray,
        sample_rate: int | None = None,
        *,
        barge: bool = False,
    ) -> str: ...

    def status(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


def _pcm16_to_wav_bytes(audio_int16: np.ndarray, sample_rate: int) -> bytes:
    """Build an in-memory mono WAV (same approach as duplex ASR)."""
    audio_int16 = np.asarray(audio_int16, dtype=np.int16).reshape(-1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return buf.getvalue()


def _write_temp_wav(audio_int16: np.ndarray, sample_rate: int) -> str:
    audio_int16 = np.asarray(audio_int16, dtype=np.int16).reshape(-1)
    fd = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    path = fd.name
    fd.close()
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return path


def asr_service_root(asr_base_url: str) -> str:
    """Strip trailing /v1 from OpenAI-compatible base URL."""
    root = (asr_base_url or "").rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root.rstrip("/") or f"http://127.0.0.1:{DEFAULT_ASR_PORT}"


def asr_health_url(asr_base_url: str) -> str:
    return f"{asr_service_root(asr_base_url)}/health"


def probe_qwen3_asr(cfg: STTConfig | None = None, *, timeout_s: float = 2.0) -> dict[str, Any]:
    """Lightweight readiness probe for the Qwen3-ASR HTTP server.

    Prefers ``/readyz`` (503 until model is warm); falls back to ``/health``.
    """
    effective = cfg or CONFIG.stt
    root = asr_service_root(effective.asr_base_url)
    readyz = f"{root}/readyz"
    health = f"{root}/health"
    try:
        import httpx

        response = httpx.get(readyz, timeout=timeout_s)
        if response.status_code == 404:
            response = httpx.get(health, timeout=timeout_s)
            url = health
        else:
            url = readyz
        if response.status_code >= 400:
            return {
                "ok": False,
                "url": url,
                "detail": (
                    f"Qwen3-ASR readiness returned HTTP {response.status_code} at {url}. "
                    "Start scripts/start-asr.ps1 (dedicated .venv-asr), "
                    "or set VA_STT_BACKEND=whisper."
                ),
            }
        payload = (
            response.json()
            if "application/json" in (response.headers.get("content-type") or "")
            else {}
        )
        if payload.get("ready") is False:
            return {
                "ok": False,
                "url": url,
                "detail": (
                    f"Qwen3-ASR is not ready yet at {url}. "
                    "Wait for model warm-up or set VA_STT_BACKEND=whisper."
                ),
            }
        return {
            "ok": True,
            "url": url,
            "model": payload.get("model") or effective.asr_model,
            "cuda": payload.get("cuda"),
            "queue_depth": payload.get("queue_depth"),
            "detail": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "url": health,
            "detail": (
                f"Qwen3-ASR is not reachable at {health} ({type(exc).__name__}: {exc}). "
                "Install the dedicated ASR env once (`scripts/start-asr.ps1` uses "
                f"`.venv-asr` + `scripts/requirements-asr.txt`, port {DEFAULT_ASR_PORT}, "
                f"not VTS {VTS_COLLISION_PORT}), or set VA_STT_BACKEND=whisper."
            ),
        }


def _httpx_timeout(cfg: STTConfig):
    import httpx

    return httpx.Timeout(
        connect=float(getattr(cfg, "asr_connect_timeout_s", 1.0) or 1.0),
        read=float(getattr(cfg, "asr_read_timeout_s", 15.0) or 15.0),
        write=float(getattr(cfg, "asr_write_timeout_s", 5.0) or 5.0),
        pool=float(getattr(cfg, "asr_pool_timeout_s", 1.0) or 1.0),
    )


class CircuitBreaker:
    """Open after N failures; cool down before allowing another attempt."""

    def __init__(self, *, max_failures: int = 3, cooldown_s: float = 30.0) -> None:
        self.max_failures = max(1, int(max_failures))
        self.cooldown_s = max(0.5, float(cooldown_s))
        self.failures = 0
        self.open_until = 0.0

    def allow(self, now: float | None = None) -> bool:
        t = float(now if now is not None else time.monotonic())
        if t < self.open_until:
            return False
        return True

    def is_open(self, now: float | None = None) -> bool:
        return not self.allow(now)

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = 0.0

    def record_failure(self, now: float | None = None) -> None:
        t = float(now if now is not None else time.monotonic())
        self.failures += 1
        if self.failures >= self.max_failures:
            self.open_until = t + self.cooldown_s


class TransientASRError(RuntimeError):
    """Safe to retry / trip the circuit (timeouts, 5xx, connect)."""


class PermanentASRError(RuntimeError):
    """Do not retry or auto-fallback (invalid audio, 4xx client errors)."""


class Qwen3ASRST:
    """OpenAI-compatible Qwen3-ASR server client."""

    def __init__(self, cfg: STTConfig | None = None, *, probe: bool = True):
        self.cfg = cfg or CONFIG.stt
        import httpx

        self._client = httpx.Client(timeout=_httpx_timeout(self.cfg))
        self._closed = False
        if probe:
            health = probe_qwen3_asr(self.cfg)
            if not health.get("ok"):
                raise RuntimeError(health.get("detail") or "Qwen3-ASR unavailable")

    def status(self) -> dict[str, Any]:
        return {
            "backend": "qwen3-asr",
            "degraded": False,
            "circuit_open": False,
            "detail": None,
            "asr_base_url": self.cfg.asr_base_url,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    def _post_once(self, wav_bytes: bytes, *, filename: str) -> str:
        import httpx

        url = f"{self.cfg.asr_base_url.rstrip('/')}/audio/transcriptions"
        lang = normalize_qwen3_asr_language(self.cfg.language)
        files = {"file": (filename, wav_bytes, "application/octet-stream")}
        data = {"model": self.cfg.asr_model}
        if lang:
            data["language"] = lang
        try:
            response = self._client.post(url, data=data, files=files)
        except httpx.TimeoutException as exc:
            raise TransientASRError(f"Qwen3-ASR timeout: {exc}") from exc
        except httpx.TransportError as exc:
            raise TransientASRError(f"Qwen3-ASR transport error: {exc}") from exc

        if response.status_code in _TRANSIENT_HTTP:
            raise TransientASRError(
                f"Qwen3-ASR HTTP {response.status_code}: {response.text[:200]}"
            )
        if 400 <= response.status_code < 500:
            raise PermanentASRError(
                f"Qwen3-ASR rejected audio (HTTP {response.status_code}): {response.text[:200]}"
            )
        response.raise_for_status()
        return str(response.json().get("text", "")).strip()

    def transcribe_bytes(self, wav_bytes: bytes, *, filename: str = "speech.wav", barge: bool = False) -> str:
        del barge
        retries = max(0, int(getattr(self.cfg, "asr_max_retries", 1) or 0))
        attempt = 0
        while True:
            try:
                return self._post_once(wav_bytes, filename=filename)
            except TransientASRError:
                if attempt >= retries:
                    raise
                attempt += 1
                log.debug("qwen3-asr transient retry %s/%s", attempt, retries)

    def transcribe_file(self, path: str, *, barge: bool = False) -> str:
        with open(path, "rb") as fh:
            return self.transcribe_bytes(fh.read(), filename=os.path.basename(path), barge=barge)

    def transcribe_array(
        self,
        audio_int16: np.ndarray,
        sample_rate: int | None = None,
        *,
        barge: bool = False,
    ) -> str:
        sr = sample_rate or self.cfg.sample_rate
        wav = _pcm16_to_wav_bytes(audio_int16, sr)
        return self.transcribe_bytes(wav, barge=barge)


class WhisperSTT:
    def __init__(self, cfg: STTConfig | None = None):
        self.cfg = cfg or CONFIG.stt
        from faster_whisper import WhisperModel

        device = resolve_torch_device(self.cfg.device, label="STT")
        compute_type = self.cfg.whisper_compute_type
        if device == "cpu" and compute_type == "float16":
            compute_type = "int8"
        self.model = WhisperModel(
            self.cfg.whisper_model,
            device=device,
            compute_type=compute_type,
        )

    def status(self) -> dict[str, Any]:
        return {
            "backend": "whisper",
            "degraded": False,
            "circuit_open": False,
            "detail": None,
            "model": self.cfg.whisper_model,
        }

    def close(self) -> None:
        return

    def transcribe_file(self, path: str, *, barge: bool = False) -> str:
        kwargs: dict = {
            "language": self.cfg.language or None,
            "beam_size": 1,
            "vad_filter": barge,
        }
        if barge:
            kwargs.update(
                no_speech_threshold=0.62,
                log_prob_threshold=-0.45,
                compression_ratio_threshold=2.2,
                condition_on_previous_text=False,
            )
        segments, _info = self.model.transcribe(path, **kwargs)
        return " ".join(seg.text.strip() for seg in segments).strip()

    def transcribe_array(
        self,
        audio_int16: np.ndarray,
        sample_rate: int | None = None,
        *,
        barge: bool = False,
    ) -> str:
        sr = sample_rate or self.cfg.sample_rate
        path = _write_temp_wav(audio_int16, sr)
        try:
            return self.transcribe_file(path, barge=barge)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


class LazyWhisperSTT:
    """Load Whisper only when fallback is actually needed."""

    def __init__(self, cfg: STTConfig | None = None) -> None:
        self.cfg = cfg or CONFIG.stt
        self._inner: WhisperSTT | None = None

    def _ensure(self) -> WhisperSTT:
        if self._inner is None:
            log.info("loading Whisper STT fallback (%s)", self.cfg.whisper_model)
            self._inner = WhisperSTT(self.cfg)
        return self._inner

    def status(self) -> dict[str, Any]:
        if self._inner is None:
            return {
                "backend": "whisper",
                "degraded": False,
                "circuit_open": False,
                "detail": "not_loaded",
                "model": self.cfg.whisper_model,
            }
        return self._inner.status()

    def close(self) -> None:
        if self._inner is not None:
            self._inner.close()

    def transcribe_array(
        self,
        audio_int16: np.ndarray,
        sample_rate: int | None = None,
        *,
        barge: bool = False,
    ) -> str:
        return self._ensure().transcribe_array(audio_int16, sample_rate, barge=barge)

    def transcribe_file(self, path: str, *, barge: bool = False) -> str:
        return self._ensure().transcribe_file(path, barge=barge)


class ResilientSTT:
    """Qwen primary with circuit breaker + optional Whisper fallback (ASR-002)."""

    def __init__(
        self,
        *,
        cfg: STTConfig,
        primary: Qwen3ASRST | None,
        fallback: LazyWhisperSTT | WhisperSTT | None,
        breaker: CircuitBreaker | None = None,
        initial_degraded: bool = False,
        detail: str | None = None,
    ) -> None:
        self.cfg = cfg
        self.primary = primary
        self.fallback = fallback
        self.breaker = breaker or CircuitBreaker(
            max_failures=int(getattr(cfg, "asr_circuit_failures", 3) or 3),
            cooldown_s=float(getattr(cfg, "asr_circuit_cooldown_s", 30.0) or 30.0),
        )
        self.degraded = bool(initial_degraded)
        self.last_error = detail
        if initial_degraded and primary is None:
            # Start with circuit open so we don't hammer a known-dead service.
            self.breaker.failures = self.breaker.max_failures
            self.breaker.open_until = time.monotonic() + self.breaker.cooldown_s

    def status(self) -> dict[str, Any]:
        return {
            "backend": "qwen3-asr" if self.primary is not None and not self.degraded else (
                "whisper" if self.degraded or self.primary is None else "qwen3-asr"
            ),
            "preferred_backend": "qwen3-asr",
            "degraded": self.degraded or self.primary is None,
            "circuit_open": self.breaker.is_open(),
            "failures": self.breaker.failures,
            "detail": self.last_error,
            "asr_base_url": self.cfg.asr_base_url,
            "fallback": self.fallback is not None,
        }

    def close(self) -> None:
        if self.primary is not None:
            self.primary.close()
        if self.fallback is not None:
            self.fallback.close()

    def _use_fallback(
        self,
        audio_int16: np.ndarray,
        sample_rate: int | None,
        *,
        barge: bool,
        reason: str,
    ) -> str:
        if self.fallback is None:
            raise RuntimeError(reason)
        self.degraded = True
        # Avoid spamming the same unreachable-ASR warning on every utterance.
        if reason and reason != self.last_error:
            log.warning("stt degraded → whisper fallback: %s", reason)
        elif not self.last_error:
            log.warning("stt degraded → whisper fallback: %s", reason)
        self.last_error = reason
        return self.fallback.transcribe_array(audio_int16, sample_rate, barge=barge)

    def transcribe_array(
        self,
        audio_int16: np.ndarray,
        sample_rate: int | None = None,
        *,
        barge: bool = False,
    ) -> str:
        if self.primary is None or self.breaker.is_open():
            return self._use_fallback(
                audio_int16,
                sample_rate,
                barge=barge,
                reason=self.last_error or "Qwen3-ASR circuit open / unavailable",
            )
        try:
            text = self.primary.transcribe_array(audio_int16, sample_rate, barge=barge)
            self.breaker.record_success()
            # Recover from degraded once primary works again.
            if self.degraded:
                log.info("stt recovered — Qwen3-ASR healthy again")
            self.degraded = False
            self.last_error = None
            return text
        except PermanentASRError:
            # Invalid audio / client error: do not burn a second expensive path.
            raise
        except TransientASRError as exc:
            self.breaker.record_failure()
            self.last_error = str(exc)
            return self._use_fallback(
                audio_int16,
                sample_rate,
                barge=barge,
                reason=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            self.breaker.record_failure()
            self.last_error = f"{type(exc).__name__}: {exc}"
            return self._use_fallback(
                audio_int16,
                sample_rate,
                barge=barge,
                reason=self.last_error,
            )

    def transcribe_file(self, path: str, *, barge: bool = False) -> str:
        if self.primary is None or self.breaker.is_open():
            if self.fallback is None:
                raise RuntimeError(self.last_error or "Qwen3-ASR unavailable")
            self.degraded = True
            return self.fallback.transcribe_file(path, barge=barge)
        try:
            text = self.primary.transcribe_file(path, barge=barge)
            self.breaker.record_success()
            self.degraded = False
            self.last_error = None
            return text
        except PermanentASRError:
            raise
        except TransientASRError as exc:
            self.breaker.record_failure()
            self.last_error = str(exc)
            if self.fallback is None:
                raise
            self.degraded = True
            log.warning("stt degraded → whisper fallback: %s", exc)
            return self.fallback.transcribe_file(path, barge=barge)
        except Exception as exc:  # noqa: BLE001
            self.breaker.record_failure()
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self.fallback is None:
                raise
            self.degraded = True
            return self.fallback.transcribe_file(path, barge=barge)


def create_stt(cfg: STTConfig | None = None, *, probe_qwen: bool = True) -> Any:
    effective = cfg or CONFIG.stt
    backend = (effective.backend or "whisper").strip().lower()
    if backend not in {"qwen3-asr", "qwen3_asr", "asr"}:
        return WhisperSTT(effective)

    fallback_enabled = bool(getattr(effective, "asr_fallback_whisper", True))
    fallback: LazyWhisperSTT | None = LazyWhisperSTT(effective) if fallback_enabled else None

    health = probe_qwen3_asr(effective) if probe_qwen else {"ok": True, "detail": None}
    if not health.get("ok"):
        detail = health.get("detail") or "Qwen3-ASR unavailable"
        if fallback is None:
            raise RuntimeError(detail)
        log.warning("qwen3-asr unavailable at startup — using Whisper fallback")
        return ResilientSTT(
            cfg=effective,
            primary=None,
            fallback=fallback,
            initial_degraded=True,
            detail=detail,
        )

    primary = Qwen3ASRST(effective, probe=False)
    return ResilientSTT(cfg=effective, primary=primary, fallback=fallback)
