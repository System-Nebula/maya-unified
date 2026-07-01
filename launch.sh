#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then PY="$ROOT/packages/voice-runtime/.venv/bin/python"; fi
if [[ ! -x "$PY" ]]; then
  echo "Missing venv. Create .venv and install packages/voice-runtime/requirements.txt" >&2
  exit 1
fi
exec "$PY" "$ROOT/launch.py" "$@"
