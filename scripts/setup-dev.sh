#!/usr/bin/env bash
# Bootstrap dev environment: uv sync with CUDA torch + voice deps.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Enter the Nix dev shell: nix develop" >&2
  exit 1
fi

echo "==> uv sync (torch cu124 + faster-qwen3-tts + platform deps)"
uv sync --extra dev

echo ""
echo "Setup complete. Next:"
echo "  source .venv/bin/activate   # or rely on 'uv run'"
echo "  make tts-check              # optional GPU smoke synth"
echo "  ./launch.sh                 # start gateway + voice agent"
