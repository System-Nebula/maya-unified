"""Manage the Qwen3-ASR HTTP sidecar started with Maya Unified.

ASR runs in ``.venv-asr`` because ``qwen-asr`` pins a different transformers
version than the main TTS stack. Port defaults to 8091 (not VTS 8001).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("maya-unified.voice.asr_sidecar")

_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
_PROC: subprocess.Popen[Any] | None = None
_OWNED = False  # True when we spawned the process (vs found an existing one)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def asr_autostart_enabled(settings: dict | None = None) -> bool:
    """Autostart when backend is qwen3-asr unless VA_ASR_AUTOSTART=0."""
    if not _env_bool("VA_ASR_AUTOSTART", True):
        return False
    backend = "whisper"
    if settings:
        backend = str((settings.get("dictation") or {}).get("backend") or backend)
    else:
        try:
            from config import CONFIG

            backend = str(CONFIG.stt.backend or backend)
        except Exception:  # noqa: BLE001
            backend = os.getenv("VA_STT_BACKEND", backend)
    return backend.strip().lower() in {"qwen3-asr", "qwen3_asr", "asr"}


def resolve_asr_bind(settings: dict | None = None) -> tuple[str, int, str, str]:
    """Return (host, port, model, base_url_v1)."""
    host = os.getenv("VA_ASR_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("VA_ASR_PORT", "8091") or 8091)
    model = os.getenv("VA_ASR_MODEL", "Qwen/Qwen3-ASR-0.6B").strip() or "Qwen/Qwen3-ASR-0.6B"
    base = ""
    if settings:
        d = settings.get("dictation") or {}
        base = str(d.get("asr_base_url") or "").strip()
        if d.get("asr_model"):
            model = str(d["asr_model"]).strip() or model
    if not base:
        base = os.getenv("VA_ASR_BASE_URL", f"http://{host}:{port}/v1").strip()
    # Prefer host/port from base URL when present.
    try:
        from urllib.parse import urlparse

        parsed = urlparse(base if "://" in base else f"http://{base}")
        if parsed.hostname:
            host = parsed.hostname
        if parsed.port:
            port = int(parsed.port)
    except Exception:  # noqa: BLE001
        pass
    if port == 8001:
        log.warning(
            "ASR port 8001 collides with VTube Studio — using 8091. "
            "Update dictation.asr_base_url to http://127.0.0.1:8091/v1"
        )
        port = 8091
        base = f"http://{host}:{port}/v1"
    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"
    return host, port, model, base


def asr_python() -> Path:
    if sys.platform == "win32":
        return _ROOT / ".venv-asr" / "Scripts" / "python.exe"
    return _ROOT / ".venv-asr" / "bin" / "python"


def asr_server_script() -> Path:
    return _ROOT / "scripts" / "asr_server.py"


def probe_asr(base_url: str, *, timeout_s: float = 1.5) -> dict[str, Any]:
    """Lightweight liveness/readiness probe against the ASR sidecar."""
    import httpx

    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    health = f"{root}/health"
    ready = f"{root}/readyz"
    try:
        with httpx.Client(timeout=timeout_s) as client:
            try:
                r = client.get(ready)
                if r.status_code == 200:
                    return {"ok": True, "ready": True, "url": ready}
                if r.status_code == 503:
                    return {"ok": True, "ready": False, "url": ready, "detail": "warming"}
            except Exception:  # noqa: BLE001
                pass
            r = client.get(health)
            if r.status_code == 200:
                return {"ok": True, "ready": False, "url": health, "detail": "alive"}
            return {"ok": False, "ready": False, "url": health, "detail": f"HTTP {r.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "ready": False,
            "url": health,
            "detail": f"{type(exc).__name__}: {exc}",
        }


def _bootstrap_venv(py: Path) -> bool:
    """Create ``.venv-asr`` and install requirements once (CUDA torch first)."""
    if not _env_bool("VA_ASR_BOOTSTRAP", True):
        log.warning(
            "ASR venv missing at %s — set VA_ASR_BOOTSTRAP=1 or run scripts/start-asr.ps1",
            py.parent.parent,
        )
        return False
    req = _ROOT / "scripts" / "requirements-asr.txt"
    venv_dir = py.parent.parent
    log.info("Creating dedicated ASR venv at %s (one-time) ...", venv_dir)
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            cwd=str(_ROOT),
        )
        subprocess.run(
            [str(py), "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            cwd=str(_ROOT),
        )
        # Match main project CUDA wheel — CPU torch makes live STT unusable.
        subprocess.run(
            [
                str(py),
                "-m",
                "pip",
                "install",
                "torch==2.7.0",
                "torchaudio==2.7.0",
                "--index-url",
                "https://download.pytorch.org/whl/cu128",
            ],
            check=True,
            cwd=str(_ROOT),
        )
        subprocess.run(
            [str(py), "-m", "pip", "install", "-r", str(req)],
            check=True,
            cwd=str(_ROOT),
        )
        subprocess.run([str(py), "-c", "import qwen_asr"], check=True, cwd=str(_ROOT))
        log.info("ASR venv ready")
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("ASR venv bootstrap failed: %s", exc)
        return False


def _venv_import_ok(py: Path) -> bool:
    if not py.is_file():
        return False
    try:
        r = subprocess.run(
            [str(py), "-c", "import qwen_asr"],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ensure_asr_sidecar(settings: dict | None = None) -> dict[str, Any]:
    """Start the ASR sidecar if needed. Safe to call multiple times."""
    global _PROC, _OWNED

    if not asr_autostart_enabled(settings):
        return {"started": False, "reason": "autostart_disabled"}

    host, port, model, base = resolve_asr_bind(settings)
    # Keep CONFIG / env / settings aligned with the bind we will use.
    os.environ["VA_ASR_HOST"] = host
    os.environ["VA_ASR_PORT"] = str(port)
    os.environ["VA_ASR_BASE_URL"] = base
    os.environ.setdefault("VA_STT_BACKEND", "qwen3-asr")
    if settings is not None:
        settings.setdefault("dictation", {})
        settings["dictation"]["asr_base_url"] = base
    try:
        from config import CONFIG

        CONFIG.stt.asr_base_url = base
    except Exception:  # noqa: BLE001
        pass

    existing = probe_asr(base, timeout_s=1.0)
    if existing.get("ok"):
        log.info(
            "ASR already running at %s (ready=%s)",
            existing.get("url"),
            existing.get("ready"),
        )
        return {"started": False, "reason": "already_running", "base_url": base, **existing}

    py = asr_python()
    if not _venv_import_ok(py):
        if not _bootstrap_venv(py) or not _venv_import_ok(py):
            return {
                "started": False,
                "reason": "venv_unavailable",
                "base_url": base,
                "detail": f"missing or broken ASR venv at {py}",
            }

    script = asr_server_script()
    if not script.is_file():
        return {"started": False, "reason": "script_missing", "detail": str(script)}

    with _LOCK:
        if _PROC is not None and _PROC.poll() is None:
            return {"started": True, "reason": "already_owned", "base_url": base, "pid": _PROC.pid}

        log_dir = _ROOT / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        out_path = log_dir / "asr_server.log"
        err_path = log_dir / "asr_server.err.log"
        out_f = open(out_path, "a", encoding="utf-8")  # noqa: SIM115
        err_f = open(err_path, "a", encoding="utf-8")  # noqa: SIM115
        cmd = [
            str(py),
            str(script),
            "--model",
            model,
            "--host",
            host,
            "--port",
            str(port),
        ]
        log.info("Starting ASR sidecar: %s", " ".join(cmd))
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        _PROC = subprocess.Popen(
            cmd,
            cwd=str(_ROOT),
            stdout=out_f,
            stderr=err_f,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        _OWNED = True
        return {
            "started": True,
            "reason": "spawned",
            "base_url": base,
            "pid": _PROC.pid,
            "host": host,
            "port": port,
            "model": model,
        }


def wait_for_asr_ready(
    settings: dict | None = None,
    *,
    timeout_s: float | None = None,
) -> bool:
    """Block until /readyz is OK or timeout. Returns True if ready."""
    _, _, _, base = resolve_asr_bind(settings)
    timeout = float(
        timeout_s
        if timeout_s is not None
        else os.getenv("VA_ASR_READY_TIMEOUT", "180") or 180
    )
    deadline = time.monotonic() + max(5.0, timeout)
    last_detail = ""
    while time.monotonic() < deadline:
        snap = probe_asr(base, timeout_s=1.5)
        if snap.get("ready"):
            log.info("ASR ready at %s", base)
            return True
        last_detail = str(snap.get("detail") or "")
        if _PROC is not None and _PROC.poll() is not None:
            log.error("ASR sidecar exited early code=%s", _PROC.returncode)
            return False
        time.sleep(1.0)
    log.warning("ASR not ready within %.0fs (%s) — continuing with Whisper fallback", timeout, last_detail)
    return False


def stop_asr_sidecar() -> None:
    """Terminate the ASR process we spawned (leave externally started servers alone)."""
    global _PROC, _OWNED
    with _LOCK:
        proc = _PROC
        owned = _OWNED
        _PROC = None
        _OWNED = False
    if not owned or proc is None:
        return
    if proc.poll() is not None:
        return
    log.info("Stopping ASR sidecar pid=%s", proc.pid)
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            try:
                proc.wait(timeout=5)
                return
            except subprocess.TimeoutExpired:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception as exc:  # noqa: BLE001
        log.warning("ASR sidecar stop failed: %s", exc)
