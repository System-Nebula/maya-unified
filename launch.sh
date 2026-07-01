#!/usr/bin/env bash
# Launch Maya Unified using the bundled qwen3-voice-agent venv.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/qwen3-voice-agent/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Missing $PY" >&2
  echo "Create it: cd qwen3-voice-agent && python -m venv .venv && pip install -r requirements.txt" >&2
  exit 1
fi
exec "$PY" "$ROOT/launch.py" "$@"
