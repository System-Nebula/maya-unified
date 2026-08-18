#!/usr/bin/env bash
# Idempotent Cloud Agent / CI bootstrap: Nix flake + uv sync.
# Does not start servers, run tests, or download TTS weights.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
. "$ROOT/scripts/install-nix-anywhere.sh"

if [[ -z "${IN_NIX_SHELL:-}" ]]; then
  exec nix develop "$ROOT" --command "$ROOT/scripts/cloud-agent-install.sh" "$@"
fi

have_nvidia() {
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1
}

echo "==> uv sync --extra dev"
if have_nvidia; then
  uv sync --extra dev
else
  echo "    no NVIDIA GPU — installing CPU torch/torchaudio wheels"
  uv sync --extra dev --no-install-package torch --no-install-package torchaudio
  uv pip install --python "$ROOT/.venv/bin/python" \
    --no-sources \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch==2.7.0+cpu" "torchaudio==2.7.0+cpu"
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "==> writing .env from .env.example (cloud/CI defaults)"
  cp "$ROOT/.env.example" "$ROOT/.env"
  # Overlay keys without clobbering a later human-edited file (first-run only).
  python3 - "$ROOT/.env" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
overrides = {
    "MAYA_PROFILE": "operator",
    "HOST": "127.0.0.1",
    "VA_TTS_ENABLED": "0",
    "VA_STT_DEVICE": "cpu",
    "ENV": "production",
    "SLSKD_HOST": "http://127.0.0.1:5030",
}
lines = text.splitlines()
seen: set[str] = set()
out: list[str] = []
for line in lines:
    key = line.split("=", 1)[0] if line and not line.lstrip().startswith("#") and "=" in line else None
    if key in overrides:
        out.append(f"{key}={overrides[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in overrides.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
fi

echo "Install complete."
