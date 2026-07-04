---
title: Testing
tags: [development, testing]
aliases: [Development/Testing]
---

# Testing

Maya Unified combines **Python unit tests** across packages and gateway apps, **integration tests** for auth and OAuth, **TTS smoke checks**, and **Playwright E2E** tests against the live dashboard. This page describes how to run each layer and where tests live.

## Quick commands

| Command | Scope |
|---------|-------|
| `make test` | Root pytest suite |
| `uv run pytest` | Same via uv |
| `make tts-check` | TTS model load smoke test |
| `make e2e-install` | Install Playwright browsers |
| `make e2e-test` | Dashboard E2E flows |

Run from repository root unless testing an isolated package.

## Unit and integration tests

### Gateway (`apps/gateway/tests/`)

| File | Coverage |
|------|----------|
| `test_operator_auth.py` | Login, session cookie, setup flow |
| `test_platform_auth.py` | Google platform login routes |
| `test_google_oauth_pkce.py` | PKCE state lifecycle |
| `test_google_integrations.py` | Connect flow, service APIs |
| `test_google_config.py` | Redirect URI configuration |

These tests typically require Postgres or use fixtures — check `conftest.py` if present for DB URL.

### Domain packages

```bash
cd packages/maya-research && uv run pytest
cd packages/maya-spider && uv run pytest
cd apps/maya-ingest && uv run pytest
```

Package `pyproject.toml` files declare `pytest` and `pytest-asyncio` under `[project.optional-dependencies].dev` or inline dev deps.

### Running with coverage (optional)

```bash
uv run pytest --cov=services --cov=apps/gateway -q
```

No enforced coverage threshold in repo — use locally for refactors touching [[Services/Voice Hub]] or auth.

## TTS verification

`make tts-check` validates that `faster-qwen3-tts` loads configured model weights on the current GPU/CPU:

- Run after [[Getting Started/Windows]] or [[Getting Started/NixOS]] setup
- Fails fast when CUDA unavailable but settings demand `device: cuda`
- Complements degraded-mode startup when TTS optional

If check fails, gateway may still start with `hub.ready` false for TTS endpoints — text chat remains testable.

## E2E tests (Playwright)

Documentation: `tests/e2e/README.md`

```bash
make e2e-install   # once per machine — downloads Chromium
make e2e-test      # assumes gateway reachable (often localhost:8090)
```

E2E scope typically includes:

- Login and setup redirect behavior
- Settings panel load
- Conversation page SSE connection (smoke)

Configure base URL via env vars documented in e2e README if non-default port.

**Tip:** Start gateway with test Postgres and known operator credentials before E2E — tests may not create operators automatically.

## Test environment setup

Minimal integration test `.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_test
SESSION_SECRET=test-secret-not-for-production
GOOGLE_CLIENT_ID=test.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=test
```

Run migrations against test database before auth/OAuth tests:

```bash
cd packages/maya-db
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_test \
  uv run alembic upgrade head
```

## CI expectations

Check `.github/workflows/` for automated jobs — typically pytest on push and docs deploy separately. Local `make test` should pass before PRs touching gateway auth or voice routes.

## Writing new tests

| Area | Guideline |
|------|-----------|
| Auth | Use AsyncClient against `apps.gateway.main:app` |
| Hub | Mock TTS/LLM when testing settings apply logic |
| Contracts | Pure Pydantic validation tests — no DB |
| OAuth | Mock Google token exchange; test PKCE state table |

Prefer testing `services/` modules directly over full GPU agent loops — voice-runtime integration remains manual/`tts-check`.

## Troubleshooting

**pytest cannot import maya_gateway**

Run `uv sync --all-packages` so workspace packages install.

**OAuth tests skip or fail DB**

Apply migrations to test DSN; ensure Postgres running.

**E2E timeout on SSE**

Gateway not running or wrong port — export `BASE_URL` per e2e README.

**CUDA tests fail on CPU-only CI**

Mark GPU tests with custom marker or run locally; gateway tests should not require GPU.

## Related documentation

- [[Development/Monorepo Conventions]] — layout
- [[Services/Operator Auth]] — auth test targets
- [[Operations/Google OAuth]] — OAuth manual QA checklist
- [[Getting Started/Prerequisites]] — dev machine requirements
