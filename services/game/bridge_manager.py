"""Spawn and track game bridge subprocesses per operator."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from services.game.deps import check_game_bridge_deps, check_vigem_available, game_bridge_deps_message

log = logging.getLogger("maya-unified.game.bridge_manager")

_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _ROOT / "data" / "game_bridge_logs"
_PYTHON = _ROOT / ".venv" / "Scripts" / "python.exe"
if not _PYTHON.is_file():
    _PYTHON = Path(sys.executable)


class BridgeManager:
    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen[Any]] = {}
        self._logs: dict[str, TextIO] = {}

    def _kill_stale_bridges(self, _operator_id: str) -> None:
        """Terminate orphan game_bridge subprocesses."""
        if sys.platform != "win32":
            return
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'apps\\.game_bridge' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("stale bridge cleanup failed: %s", exc)

    def _read_log_tail(self, operator_id: str, *, max_lines: int = 20) -> list[str]:
        path = _LOG_DIR / f"{operator_id}.log"
        if not path.is_file():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-max_lines:]
        except Exception:  # noqa: BLE001
            return []

    def status(self, operator_id: str) -> dict[str, Any]:
        oid = str(operator_id)
        proc = self._procs.get(oid)
        if proc is None:
            tail = self._read_log_tail(oid)
            out: dict[str, Any] = {"running": False}
            if tail:
                out["log_tail"] = tail
            return out
        code = proc.poll()
        if code is not None:
            self._procs.pop(oid, None)
            log_file = self._logs.pop(oid, None)
            if log_file is not None:
                try:
                    log_file.close()
                except Exception:  # noqa: BLE001
                    pass
            tail = self._read_log_tail(oid)
            out = {"running": False, "exit_code": code}
            if tail:
                out["log_tail"] = tail
            return out
        return {"running": True, "pid": proc.pid}

    def start(
        self,
        operator_id: str,
        *,
        profile_id: str,
        gateway: str,
        token: str,
        goal: str = "",
    ) -> dict[str, Any]:
        oid = str(operator_id)
        if not token:
            return {"ok": False, "error": "session token required"}
        missing = check_game_bridge_deps()
        if missing:
            msg = game_bridge_deps_message(missing)
            log.error("game bridge deps missing: %s", missing)
            return {"ok": False, "error": msg}
        self._kill_stale_bridges(oid)
        self.stop(oid)
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{oid}.log"
        log_file = log_path.open("a", encoding="utf-8")
        log_file.write(f"\n--- bridge start profile={profile_id} ---\n")
        log_file.flush()
        cmd = [
            str(_PYTHON),
            "-m",
            "apps.game_bridge",
            "run",
            "--profile",
            profile_id,
            "--gateway",
            gateway.rstrip("/"),
            "--token",
            token,
            "-v",
        ]
        if goal.strip():
            cmd.extend(["--goal", goal.strip()])
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("bridge start failed")
            try:
                log_file.close()
            except Exception:  # noqa: BLE001
                pass
            return {"ok": False, "error": str(exc)}
        self._procs[oid] = proc
        self._logs[oid] = log_file

        def _watch() -> None:
            proc.wait()
            try:
                log_file.write(f"\n--- bridge exit code={proc.returncode} ---\n")
                log_file.flush()
                log_file.close()
            except Exception:  # noqa: BLE001
                pass
            self._logs.pop(oid, None)

        threading.Thread(target=_watch, daemon=True, name=f"bridge-watch-{oid[:8]}").start()
        log.info("game bridge started pid=%s profile=%s operator=%s", proc.pid, profile_id, oid)
        return {"ok": True, "pid": proc.pid, "profile_id": profile_id, "log": str(log_path)}

    def stop(self, operator_id: str) -> dict[str, Any]:
        oid = str(operator_id)
        proc = self._procs.pop(oid, None)
        log_file = self._logs.pop(oid, None)
        if proc is None:
            return {"ok": True, "stopped": False}
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        if log_file is not None:
            try:
                log_file.close()
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "stopped": True}


bridge_manager = BridgeManager()
