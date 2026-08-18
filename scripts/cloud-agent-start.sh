#!/usr/bin/env bash
# Per-boot runtime: Postgres + migrations + strong SESSION_SECRET.
# Must terminate; the gateway runs from environment.json terminals.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
. "$ROOT/scripts/install-nix-anywhere.sh"

if [[ -z "${IN_NIX_SHELL:-}" ]]; then
  exec nix develop "$ROOT" --command "$ROOT/scripts/cloud-agent-start.sh" "$@"
fi

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public}"
# Nix `psql`/`pg_isready` are libpq clients. GHA's Postgres service uses
# password auth; without PGPASSWORD they prompt: "no password supplied".
eval "$(python3 "$ROOT/scripts/pg_env_from_database_url.py")"
SECRET_FILE="$ROOT/data/session_secret"
mkdir -p "$ROOT/data"

ensure_session_secret() {
  local current="${SESSION_SECRET:-}"
  if [[ ${#current} -ge 16 ]]; then
    case "${current,,}" in
      change-me-in-production|changeme|change-me|dev-insecure-change-me|secret|password|maya|maya-secret)
        ;;
      *)
        return 0
        ;;
    esac
  fi
  if [[ -f "$SECRET_FILE" ]]; then
    SESSION_SECRET="$(tr -d '[:space:]' < "$SECRET_FILE")"
    if [[ ${#SESSION_SECRET} -ge 16 ]]; then
      export SESSION_SECRET
      return 0
    fi
  fi
  SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  umask 077
  printf '%s\n' "$SESSION_SECRET" > "$SECRET_FILE"
  export SESSION_SECRET
  echo "wrote SESSION_SECRET to $SECRET_FILE"
}

pg_ready() {
  command -v pg_isready >/dev/null 2>&1 \
    && pg_isready -h 127.0.0.1 -p 5432 -U postgres -d maya_public >/dev/null 2>&1
}

wait_pg() {
  local i
  for i in $(seq 1 60); do
    if pg_ready; then
      return 0
    fi
    sleep 1
  done
  echo "postgres did not become ready on 127.0.0.1:5432" >&2
  return 1
}

start_docker_postgres() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    return 1
  fi
  echo "==> docker compose postgres"
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$ROOT/infra/docker-compose.postgres.yml" up -d
  else
    docker-compose -f "$ROOT/infra/docker-compose.postgres.yml" up -d
  fi
  wait_pg
}

start_nix_postgres() {
  local pgdata="$ROOT/data/postgres"
  export PGDATA="$pgdata"
  export PGUSER="${PGUSER:-postgres}"
  if ! command -v initdb >/dev/null 2>&1 || ! command -v pg_ctl >/dev/null 2>&1; then
    echo "postgresql client/server tools missing from nix develop" >&2
    return 1
  fi
  echo "==> nix postgresql at $pgdata"
  if [[ ! -f "$pgdata/PG_VERSION" ]]; then
    mkdir -p "$pgdata"
    initdb --username=postgres --auth-host=trust --auth-local=trust --pgdata="$pgdata"
  fi
  if ! pg_ready; then
    pg_ctl -D "$pgdata" -l "$ROOT/data/postgres.log" -o "-h 127.0.0.1 -p 5432 -k /tmp" start
  fi
  wait_pg
  if command -v createdb >/dev/null 2>&1; then
    createdb -h 127.0.0.1 -U postgres maya_public 2>/dev/null || true
  fi
  psql -h 127.0.0.1 -U postgres -d maya_public -v ON_ERROR_STOP=1 \
    -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";' \
    -c 'CREATE EXTENSION IF NOT EXISTS pgcrypto;' \
    -c 'CREATE EXTENSION IF NOT EXISTS vector;' \
    >/dev/null
}

ensure_session_secret

if ! pg_ready; then
  start_docker_postgres || start_nix_postgres
fi

if ! pg_ready; then
  echo "failed to start postgres" >&2
  exit 1
fi

echo "==> postgres extensions"
psql -h 127.0.0.1 -U postgres -d maya_public -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";' \
  -c 'CREATE EXTENSION IF NOT EXISTS pgcrypto;' \
  -c 'CREATE EXTENSION IF NOT EXISTS vector;' \
  >/dev/null

echo "==> alembic upgrade heads"
( cd "$ROOT/packages/maya-db" && uv run --no-sync alembic upgrade heads )

echo "==> openbao"
if "$ROOT/scripts/start-openbao.sh"; then
  echo "openbao ready"
else
  echo "openbao skipped (docker/nix unavailable or not ready)"
fi

echo "==> slskd"
if "$ROOT/scripts/start-slskd.sh"; then
  echo "slskd ready"
else
  echo "slskd skipped (docker/nix unavailable or not ready)"
fi

echo "Start complete (postgres ready, schema migrated)."
