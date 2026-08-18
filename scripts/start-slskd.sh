#!/usr/bin/env bash
# Start slskd (Docker compose, then nixpkgs slskd). Idempotent. Exits 0 when :5030 is ready.
# Soulseek login comes from OpenBao (secret/maya/integrations/slskd) unless env is already set.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE="$ROOT/infra/docker-compose.slskd.yml"
KEY_FILE="$ROOT/data/slskd_api_key"
MODE_FILE="$ROOT/data/slskd_mode"
mkdir -p "$ROOT/data/slskd/app" "$ROOT/data/slskd/downloads" "$ROOT/data/slskd/shared"

if [[ -z "${BAO_ADDR:-}" ]]; then
  BAO_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
fi
export BAO_ADDR="${BAO_ADDR:-http://127.0.0.1:8200}"
if [[ -z "${BAO_TOKEN:-}" && -f "$ROOT/data/openbao_root_token" ]]; then
  BAO_TOKEN="$(tr -d '[:space:]' < "$ROOT/data/openbao_root_token")"
  export BAO_TOKEN
fi

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

slskd_logged_in() {
  python3 - <<'PY'
import json, os, sys, urllib.error, urllib.request
host = (os.environ.get("SLSKD_HOST") or "http://127.0.0.1:5030").rstrip("/")
key = os.environ.get("SLSKD_API_KEY") or ""
if not key:
    sys.exit(1)
req = urllib.request.Request(
    f"{host}/api/v0/application",
    headers={"X-API-Key": key, "Accept": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=2) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
    sys.exit(1)
server = payload.get("server") if isinstance(payload, dict) else None
if isinstance(server, dict) and server.get("isLoggedIn"):
    sys.exit(0)
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

load_openbao_creds() {
  if [[ -z "${SLSKD_SLSK_USERNAME:-}" || -z "${SLSKD_SLSK_PASSWORD:-}" ]]; then
    eval "$(PYTHONPATH="$ROOT" python3 -m services.secrets.openbao)"
  fi
}

stop_listening_slskd() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx maya-slskd; then
      echo "==> stopping docker slskd (not logged in; applying OpenBao creds)"
      if docker compose version >/dev/null 2>&1; then
        docker compose -f "$COMPOSE" down
      else
        docker-compose -f "$COMPOSE" down
      fi
      return 0
    fi
  fi
  echo "==> stopping nix slskd (not logged in; applying OpenBao creds)"
  python3 - <<'PY'
import os, signal, time
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            cmd = handle.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        continue
    if "slskd" in cmd and (
        "--http-port 5030" in cmd or "slskd_example" in cmd
    ):
        os.kill(int(pid), signal.SIGTERM)
        break
time.sleep(1)
PY
}

start_example_slskd() {
  echo "==> example slskd (bundled test account, no Soulseek network)"
  nohup env PYTHONPATH="$ROOT" SLSKD_API_KEY="$SLSKD_API_KEY" \
    python3 -m services.slskd_example.server \
    >/tmp/slskd-example.log 2>&1 &
  printf 'example\n' > "$MODE_FILE"
}

start_docker_slskd() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    return 1
  fi
  echo "==> docker compose slskd"
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE" up -d
  else
    docker-compose -f "$COMPOSE" up -d
  fi
}

start_nix_slskd() {
  if ! command -v nix >/dev/null 2>&1; then
    return 1
  fi
  echo "==> nix slskd"
  nohup nix shell nixpkgs#slskd --command slskd \
    --app-dir "$ROOT/data/slskd/app" \
    --http-port 5030 \
    --https-port 5031 \
    --no-https \
    --api-key "$SLSKD_API_KEY" \
    --downloads "$ROOT/data/slskd/downloads" \
    --shared "$ROOT/data/slskd/shared" \
    >/tmp/slskd-nix.log 2>&1 &
}

load_openbao_creds
export SLSKD_HOST="${SLSKD_HOST:-http://127.0.0.1:5030}"
ensure_api_key

use_example=0
case "${SLSKD_EXAMPLE:-}" in
  1|true|TRUE|yes|YES) use_example=1 ;;
esac

if slskd_listening; then
  if slskd_logged_in; then
    echo "slskd already listening on 127.0.0.1:5030"
    exit 0
  fi
  if [[ "$use_example" -eq 1 || ( -n "${SLSKD_SLSK_USERNAME:-}" && -n "${SLSKD_SLSK_PASSWORD:-}" ) ]]; then
    stop_listening_slskd
  else
    echo "slskd already listening on 127.0.0.1:5030 (not logged in; no OpenBao/env Soulseek creds)"
    exit 0
  fi
fi

if [[ "$use_example" -eq 1 ]]; then
  start_example_slskd
elif [[ -z "${SLSKD_SLSK_USERNAME:-}" || -z "${SLSKD_SLSK_PASSWORD:-}" ]]; then
  echo "slskd Soulseek login missing; seeding bundled example test account" >&2
  start_example_slskd
else
  printf 'soulseek\n' > "$MODE_FILE"
  start_docker_slskd || start_nix_slskd || {
    echo "real slskd unavailable; falling back to bundled example" >&2
    start_example_slskd
  }
fi

for _ in $(seq 1 60); do
  if slskd_listening; then
    echo "slskd ready on 127.0.0.1:5030"
    exit 0
  fi
  sleep 1
done

echo "slskd did not become ready on 127.0.0.1:5030" >&2
if [[ -f /tmp/slskd-example.log ]]; then
  tail -n 40 /tmp/slskd-example.log >&2 || true
fi
if [[ -f /tmp/slskd-nix.log ]]; then
  tail -n 40 /tmp/slskd-nix.log >&2 || true
fi
exit 1
