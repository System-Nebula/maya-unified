#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Re-exec inside nix develop when launched from a plain shell so libportaudio,
# ffmpeg, and CUDA runtime libs are on the loader path.
if [[ -z "${IN_NIX_SHELL:-}" && -z "${MAYA_NIX_REEXEC:-}" ]] && command -v nix >/dev/null 2>&1; then
  exec env MAYA_NIX_REEXEC=1 nix develop "$ROOT" -c "$ROOT/launch.sh" "$@"
fi

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then PY="$ROOT/packages/voice-runtime/.venv/bin/python"; fi
if [[ ! -x "$PY" ]]; then
  echo "Missing venv. Create .venv and install packages/voice-runtime/requirements.txt" >&2
  exit 1
fi
export UV_PYTHON="$PY"
export PYTHONNOUSERSITE=1
unset PYTHONHOME
exec "$PY" -I "$ROOT/launch.py" "$@"
