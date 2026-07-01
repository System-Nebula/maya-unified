#!/usr/bin/env python3
"""Single entrypoint for Maya Unified gateway + voice agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from services.paths import setup_paths, VOICE_AGENT

setup_paths()

# Prefer the bundled qwen3 venv when present.
_qwen3_python = (
    VOICE_AGENT / ".venv" / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else VOICE_AGENT / ".venv" / "bin" / "python"
)
if _qwen3_python.is_file() and Path(sys.executable).resolve() != _qwen3_python.resolve():
    print(
        f"Tip: run with the qwen3 venv for voice deps:\n  {_qwen3_python} {Path(__file__).name}",
        file=sys.stderr,
    )

# Load .env from maya-unified then bundled qwen3-voice-agent
for env_file in (ROOT / ".env", VOICE_AGENT / ".env"):
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = val.strip().strip('"').strip("'")

os.environ.setdefault("PORT", "8090")


def _check_voice_deps() -> str | None:
    """Return a user-facing message when qwen3 runtime deps are missing."""
    try:
        import faster_qwen3_tts  # noqa: F401
        import faster_whisper  # noqa: F401
    except ImportError as exc:
        return (
            "Voice agent Python packages are not installed. From the repo root run:\n"
            "  pip install -r qwen3-voice-agent/requirements.txt\n"
            "  (install PyTorch for your GPU first — see qwen3-voice-agent/README.md)\n"
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
