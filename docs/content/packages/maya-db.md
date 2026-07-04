---
title: Maya DB
tags: [packages, database, postgres]
aliases: [Packages/Maya DB]
---

# Maya DB

`packages/maya-db/` owns PostgreSQL connectivity for Maya Unified: SQLAlchemy 2.x async models, Alembic migration history, and the session factory used by gateway auth, Google OAuth, voice rooms, and platform features. Without this package and a running Postgres instance, operator login, OAuth, and platform APIs cannot function — though the voice engine itself can still run in degraded text-only mode.

## Package structure

```
packages/maya-db/
├── pyproject.toml
├── alembic.ini
├── migrations/
│   └── versions/          # timestamped migration scripts
└── src/maya_db/
    ├── __init__.py
    └── models/
        ├── operator.py              # operator_users
        ├── google_integration.py    # oauth + google_connections
        ├── operator_voice.py        # per-operator voice metadata
        ├── voice_room.py            # voice rooms + guest sessions
        └── __init__.py
```

Dependencies include `sqlalchemy>=2.0`, `asyncpg`, `alembic`, `pgvector`, and `psycopg2-binary` (sync fallback for scripts).

## Core tables

| Table | Model file | Purpose |
|-------|------------|---------|
| `operator_users` | `models/operator.py` | Dashboard operators — username, password hash, role, ban flag |
| `oauth_pkce_states` | `models/google_integration.py` | Short-lived PKCE state for Google login and connect flows |
| `operator_google_identities` | `models/google_integration.py` | Links Google account to operator for platform sign-in |
| `google_connections` | `models/google_integration.py` | Connected integration metadata (refresh tokens on disk) |
| `voice_rooms` | `models/voice_room.py` | Multi-user voice room definitions and slugs |
| Arena / registry / research | various migrations | Platform entities when full stack enabled |

Operator roles are validated in `services/auth/operator_store.py`: `admin` (manage operators, workspaces) and `operator` (standard dashboard access).

## How sessions reach the gateway

```mermaid
flowchart LR
    ENV["DATABASE_URL env"]
    OS["services/auth/operator_store.py"]
    DEP["services/auth/deps.py"]
    RT["FastAPI routes"]

    ENV --> OS
    OS -->|async session generator| DEP
    DEP -->|require_operator / require_admin| RT
```

`get_db_session()` yields an `AsyncSession` bound to the engine created from `DATABASE_URL`. The auth middleware in `apps/gateway/main.py` resolves operators from the signed `maya_op_session` cookie on protected routes.

## Running migrations

From the package directory:

```bash
cd packages/maya-db
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public \
  uv run alembic upgrade head
```

Or with Python directly:

```bash
DATABASE_URL=postgresql+asyncpg://maya:maya@localhost:5433/maya \
  python -m alembic upgrade head
```

Alembic reads `alembic.ini` and discovers models via the env script. Always run migrations before starting the gateway when setting up a fresh database.

Recent migration themes (check `migrations/versions/` for exact filenames):

- `operator_users_*` — operator auth foundation
- `google_integrations_*`, `oauth_pkce_*` — [[Operations/Google OAuth]]
- `operator_voice_*` — per-operator voice preferences in DB
- `voice_rooms_*` — guest room support
- `image_jobs_*`, arena tables — [[Packages/Maya Image]] platform

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | *(none — required for auth)* | Async Postgres DSN, e.g. `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `DATABASE_URL` in settings.json | `""` | Optional override under `platform.database_url` in unified settings |

The gateway loads `.env` from repo root and `packages/voice-runtime/.env` via `services/env_loader.py`. Platform settings can mirror `DATABASE_URL` into the dashboard settings panel under **Platform**, but the env var takes precedence at process start.

## pgvector

The package depends on `pgvector` for embedding-backed features in research and discover pipelines. Ensure your Postgres instance has the extension available:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

If the extension is missing, migrations or runtime queries that touch vector columns will fail with a clear Postgres error.

## Troubleshooting

**503 "OAuth tables missing" or auth routes return schema errors**

Run `alembic upgrade head`. The helper `services/integrations/google/db_errors.py` detects missing tables and surfaces actionable 503 responses.

**`asyncpg` connection refused**

Confirm Postgres is listening, credentials match `DATABASE_URL`, and the database exists. Docker Compose examples often map port `5433` externally while `5432` is internal — match the host port in your DSN.

**Operator login works but platform routes warn "unavailable"**

Platform routes import `maya_gateway` packages separately from `maya-db`. A missing `uv sync --all-packages` causes import failures unrelated to DB connectivity. Check gateway logs for `platform routes unavailable`.

**Migration conflicts after pulling main**

If two branches add migrations, Alembic may require a merge revision (see `merge_google_operator_20260705.py` pattern). Run `alembic heads` to inspect; create a merge migration if multiple heads exist.

## Related documentation

- [[Services/Operator Auth]] — how operators are stored and verified
- [[Operations/Google OAuth]] — OAuth table usage
- [[Operations/Deployment]] — production Postgres checklist
- [[Packages/Maya Contracts]] — API shapes above the DB layer
- [[Configuration/Environment Variables]] — full `DATABASE_URL` documentation
