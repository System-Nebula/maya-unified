#!/usr/bin/env bash
# Load OpenBao postgres (and token file) into the environment, then exec.
# Explicit DATABASE_URL / PG* already in the environment still win.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${BAO_ADDR:-}" ]]; then
  export BAO_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
fi
if [[ -z "${BAO_TOKEN:-}" && -n "${VAULT_TOKEN:-}" ]]; then
  export BAO_TOKEN="$VAULT_TOKEN"
fi
if [[ -z "${BAO_TOKEN:-}" && -f "$ROOT/data/openbao_root_token" ]]; then
  BAO_TOKEN="$(tr -d '[:space:]' < "$ROOT/data/openbao_root_token")"
  export BAO_TOKEN
fi

eval "$(PYTHONPATH="$ROOT" python3 -m services.secrets.openbao db)"

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <command> [args...]" >&2
  exit 2
fi
exec "$@"
