#!/usr/bin/env bash
# Start local OpenBao on :8200 if nothing is already listening.
# Prefer an existing BAO_ADDR (remote OpenBao); otherwise Docker compose, then nixpkgs openbao -dev.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE="$ROOT/infra/docker-compose.openbao.yml"
TOKEN_FILE="$ROOT/data/openbao_root_token"
mkdir -p "$ROOT/data"

if [[ -z "${BAO_ADDR:-}" ]]; then
  BAO_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
fi
if [[ -z "${BAO_ADDR:-}" ]]; then
  BAO_ADDR="http://127.0.0.1:8200"
fi
export BAO_ADDR

bao_listening() {
  local host="${1:-127.0.0.1}"
  local port="${2:-8200}"
  python3 - "$host" "$port" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
try:
    with socket.create_connection((host, port), timeout=0.5):
        sys.exit(0)
except OSError:
    sys.exit(1)
PY
}

bao_host_port() {
  python3 - <<'PY'
import os, urllib.parse
addr = os.environ.get("BAO_ADDR") or "http://127.0.0.1:8200"
parsed = urllib.parse.urlparse(addr)
host = parsed.hostname or "127.0.0.1"
port = parsed.port or (443 if parsed.scheme == "https" else 80)
if parsed.scheme == "http" and parsed.port is None:
    port = 8200
print(host)
print(port)
PY
}

bao_is_local() {
  python3 - <<'PY'
import os, urllib.parse, sys
addr = os.environ.get("BAO_ADDR") or "http://127.0.0.1:8200"
host = urllib.parse.urlparse(addr).hostname or ""
sys.exit(0 if host in ("127.0.0.1", "localhost", "::1") else 1)
PY
}

ensure_token() {
  if [[ -n "${BAO_TOKEN:-}" ]]; then
    return 0
  fi
  if [[ -n "${VAULT_TOKEN:-}" ]]; then
    BAO_TOKEN="$VAULT_TOKEN"
    export BAO_TOKEN
    return 0
  fi
  if [[ -f "$TOKEN_FILE" ]]; then
    BAO_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
    if [[ -n "$BAO_TOKEN" ]]; then
      export BAO_TOKEN
      return 0
    fi
  fi
  if ! bao_is_local; then
    echo "openbao: remote BAO_ADDR requires BAO_TOKEN (or VAULT_TOKEN)" >&2
    return 1
  fi
  BAO_TOKEN="${BAO_DEV_ROOT_TOKEN_ID:-maya-dev-root}"
  umask 077
  printf '%s\n' "$BAO_TOKEN" > "$TOKEN_FILE"
  export BAO_TOKEN
  export BAO_DEV_ROOT_TOKEN_ID="$BAO_TOKEN"
}

seed_slskd() {
  PYTHONPATH="$ROOT" python3 -m services.secrets.openbao init-dev || true
}

ensure_token
HOST_PORT="$(bao_host_port)"
BAO_HOST="$(printf '%s\n' "$HOST_PORT" | sed -n '1p')"
BAO_PORT="$(printf '%s\n' "$HOST_PORT" | sed -n '2p')"

if bao_listening "$BAO_HOST" "$BAO_PORT"; then
  echo "openbao already listening on ${BAO_HOST}:${BAO_PORT}"
  seed_slskd
  exit 0
fi

if ! bao_is_local; then
  echo "waiting for remote OpenBao at $BAO_ADDR" >&2
  for _ in $(seq 1 30); do
    if bao_listening "$BAO_HOST" "$BAO_PORT"; then
      echo "openbao ready at $BAO_ADDR"
      seed_slskd
      exit 0
    fi
    sleep 1
  done
  echo "remote OpenBao at $BAO_ADDR is not reachable" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "==> docker compose openbao"
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE" up -d
  else
    docker-compose -f "$COMPOSE" up -d
  fi
else
  echo "==> nix openbao -dev"
  if ! command -v nix >/dev/null 2>&1; then
    echo "openbao: neither docker nor nix is available" >&2
    exit 1
  fi
  nohup nix shell nixpkgs#openbao --command bao server \
    -dev \
    -dev-listen-address=127.0.0.1:8200 \
    -dev-root-token-id="$BAO_TOKEN" \
    >/tmp/openbao-dev.log 2>&1 &
fi

for _ in $(seq 1 60); do
  if bao_listening 127.0.0.1 8200; then
    echo "openbao ready on 127.0.0.1:8200"
    seed_slskd
    exit 0
  fi
  sleep 1
done

echo "openbao did not become ready on 127.0.0.1:8200" >&2
if [[ -f /tmp/openbao-dev.log ]]; then
  tail -n 40 /tmp/openbao-dev.log >&2 || true
fi
exit 1
