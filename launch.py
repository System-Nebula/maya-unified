#!/usr/bin/env python3
"""Single entrypoint for Maya Unified gateway + voice agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from services.paths import setup_paths, VOICE_RUNTIME

setup_paths()

if sys.platform == "win32":
    _venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    _legacy_venv = VOICE_RUNTIME / ".venv" / "Scripts" / "python.exe"
else:
    _venv_python = ROOT / ".venv" / "bin" / "python"
    _legacy_venv = VOICE_RUNTIME / ".venv" / "bin" / "python"

for candidate in (_venv_python, _legacy_venv):
    if candidate.is_file() and Path(sys.executable).resolve() != candidate.resolve():
        print(
            f"Tip: run with the project venv for voice deps:\n  {candidate} {Path(__file__).name}",
            file=sys.stderr,
        )
        break

from services.env_loader import load_env_files

load_env_files(ROOT / ".env", VOICE_RUNTIME / ".env")

os.environ.setdefault("PORT", "8090")


def _check_voice_deps() -> str | None:
    """Return a user-facing message when voice runtime deps are missing."""
    try:
        import faster_qwen3_tts  # noqa: F401
        import faster_whisper  # noqa: F401
    except ImportError as exc:
        return (
            "Voice runtime packages are not installed. From the repo root run:\n"
            "  setup_windows.bat   (Windows)\n"
            "  or: pip install -r packages/voice-runtime/requirements.txt\n"
            "  (install PyTorch for your GPU first)\n"
            f"Detail: {exc}"
        )
    return None


def main() -> None:
    missing = _check_voice_deps()
    if missing:
        print(missing, file=sys.stderr)
    from apps.gateway.main import run

    run()


if __name__ == "__main__":
    main()
