#!/usr/bin/env bash
# Start slskd via Docker compose. Idempotent. Exits 0 when :5030 is ready.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE="$ROOT/infra/docker-compose.slskd.yml"
KEY_FILE="$ROOT/data/slskd_api_key"
mkdir -p "$ROOT/data/slskd/app" "$ROOT/data/slskd/downloads" "$ROOT/data/slskd/shared"

slskd_listening() {
  python3 - <<'PY'
import socket
import sys
try:
    with socket.create_connection(("127.0.0.1", 5030), timeout=0.5):
        sys.exit(0)
except OSError:
    sys.exit(1)
PY
}

ensure_api_key() {
  local current="${SLSKD_API_KEY:-}"
  if [[ ${#current} -ge 16 ]]; then
    export SLSKD_API_KEY="$current"
    return 0
  fi
  if [[ -f "$KEY_FILE" ]]; then
    SLSKD_API_KEY="$(tr -d '[:space:]' < "$KEY_FILE")"
    if [[ ${#SLSKD_API_KEY} -ge 16 ]]; then
      export SLSKD_API_KEY
      return 0
    fi
  fi
  SLSKD_API_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  umask 077
  printf '%s\n' "$SLSKD_API_KEY" > "$KEY_FILE"
  export SLSKD_API_KEY
  echo "wrote SLSKD_API_KEY to $KEY_FILE"
}

export SLSKD_HOST="${SLSKD_HOST:-http://127.0.0.1:5030}"
ensure_api_key

if slskd_listening; then
  echo "slskd already listening on 127.0.0.1:5030"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not available; cannot start slskd" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "docker daemon not reachable; cannot start slskd" >&2
  exit 1
fi

echo "==> docker compose slskd"
if docker compose version >/dev/null 2>&1; then
  docker compose -f "$COMPOSE" up -d
else
  docker-compose -f "$COMPOSE" up -d
fi

for _ in $(seq 1 60); do
  if slskd_listening; then
    echo "slskd ready on 127.0.0.1:5030"
    exit 0
  fi
  sleep 1
done

echo "slskd did not become ready on 127.0.0.1:5030" >&2
exit 1
