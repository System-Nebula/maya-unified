# Google OAuth — platform login and app integrations

> **Canonical docs:** [operations/google-oauth](https://system-nebula.github.io/maya-unified/operations/google-oauth) on the docs site. This file is kept as a repo-local reference.

Maya Unified supports two separate Google OAuth flows:

1. **Platform sign-in** — authenticate an operator via Google (login page).
2. **App integration connect** — link Gmail/Calendar scopes for an already-signed-in operator (Settings → Integrations).

Both flows use PKCE, persist short-lived state in Postgres, and honor dynamic redirect URIs derived from the browser host when `MAYA_OAUTH_DYNAMIC_REDIRECT=1`.

## Architecture

```
Login flow
  GET /api/platform/auth/login/google
    → store oauth_pkce_states (verifier, redirect_uri, flow=login)
    → redirect to Google with code_challenge (S256)
  GET /auth/google/callback  (legacy path; also /api/platform/auth/callback/google)
    → exchange code + stored verifier for tokens
    → link operator_google_identities or match by email/username
    → set maya_op_session cookie

Connect flow
  GET /api/integrations/google/connect?permissions=mailbox_read,calendar_read
    → require operator session
    → store oauth_pkce_states (flow=connect, operator_id)
  GET /api/integrations/google/callback
    → exchange code, write refresh token to disk
    → upsert google_connections row
    → redirect to /settings?tab=integrations
```

### Code layout

| Path | Purpose |
|------|---------|
| `services/integrations/google/config.py` | Env vars, dynamic redirect URI, Console checklist |
| `services/integrations/google/oauth.py` | PKCE pair generation, Flow helpers, token exchange |
| `services/integrations/google/scopes.py` | Permission groups → Google scopes |
| `services/integrations/google/token_store.py` | Refresh tokens on disk (`MAYA_GOOGLE_TOKEN_DIR`) |
| `services/integrations/google/service.py` | Gmail inbox + Calendar event reads |
| `apps/gateway/platform_auth_routes.py` | Platform login + callback |
| `apps/gateway/google_integrations_routes.py` | Connect, status, disconnect, service APIs |
| `apps/dashboard/js/mayaIntegrations.js` | Settings → Integrations UI |

### Database tables

| Table | Purpose |
|-------|---------|
| `oauth_pkce_states` | Short-lived PKCE state, verifier, redirect_uri, flow |
| `operator_google_identities` | Links Google account to operator for sign-in |
| `google_connections` | Connected integration metadata (tokens on disk) |

Run migrations:

```bash
cd packages/maya-db
DATABASE_URL=postgresql+asyncpg://maya:maya@localhost:5433/maya \
  python -m alembic upgrade head
```

## Google Cloud Console setup

1. Create or select a **Web application** OAuth client.
2. Copy **Client ID** and **Client secret** into `.env`.
3. Register **Authorized redirect URIs** (all six for local dev):

```
http://localhost:8090/auth/google/callback
http://localhost:8090/api/platform/auth/callback/google
http://localhost:8090/api/integrations/google/callback
http://127.0.0.1:8090/auth/google/callback
http://127.0.0.1:8090/api/platform/auth/callback/google
http://127.0.0.1:8090/api/integrations/google/callback
```

4. Register **Authorized JavaScript origins**:

```
http://localhost:8090
http://127.0.0.1:8090
```

5. Delete any empty URI rows before clicking **Save**.

Print the live checklist and probe redirect URI:

```bash
python scripts/verify_google_oauth.py
```

Status endpoint (when gateway is running):

```bash
curl -s http://localhost:8090/api/platform/auth/status | python3 -m json.tool
```

## Environment variables

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MAYA_APP_BASE_URL=http://localhost:8090
MAYA_OAUTH_DYNAMIC_REDIRECT=1
GOOGLE_LOGIN_REDIRECT_URI=http://localhost:8090/auth/google/callback
GOOGLE_CONNECT_REDIRECT_URI=http://localhost:8090/api/integrations/google/callback
MAYA_GOOGLE_TOKEN_DIR=.data/google-tokens
```

| Variable | Notes |
|----------|-------|
| `MAYA_OAUTH_DYNAMIC_REDIRECT` | When `1`, redirect URI follows browser host (`localhost` vs `127.0.0.1`) |
| `GOOGLE_REDIRECT_URI` | Legacy alias for login redirect |
| `MAYA_GOOGLE_TOKEN_DIR` | Refresh tokens stored here (gitignored via `.data/`) |

Shell exports of OAuth vars are overridden by `.env` on startup (`services/env_loader.py`).

## Permission groups

| Permission | Google scopes |
|------------|---------------|
| `mailbox_read` | `gmail.readonly` |
| `mailbox_send` | `gmail.compose`, `gmail.send`, `gmail.modify` |
| `calendar_read` | `calendar.readonly` |
| `calendar_write` | `calendar` |

Default connect permissions: `mailbox_read`, `calendar_read`.

## Operator linking rules

Google sign-in succeeds only when:

- An `operator_google_identities` row exists for the Google account, or
- An operator username matches the Google email (full address or local part before `@`).

Otherwise the callback returns **403** with guidance to sign in with email first and connect Google in Settings.

## Service APIs (authenticated operator)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/integrations/google/status` | Connection state and granted permissions |
| `GET /api/integrations/google/connect` | Start connect OAuth |
| `DELETE /api/integrations/google` | Disconnect and delete stored tokens |
| `GET /api/services/email/inboxes` | List inbox threads (requires `mailbox_read`) |
| `GET /api/services/calendar/events` | List calendar events (requires `calendar_read`) |

## Troubleshooting

### Error 400: redirect_uri_mismatch

The `redirect_uri` sent to Google must exactly match a registered URI for **this** client ID.

- Run `python scripts/verify_google_oauth.py` and compare `Live redirect_uri` to Console.
- Ensure Console changes are saved (empty URI rows block Save).
- Use the same host you registered (`localhost` or `127.0.0.1`, not both interchangeably unless both are registered).

### Invalid code verifier / Internal Server Error on callback

PKCE requires the same verifier/challenge pair in the auth URL and token exchange. If you see this after a code change, start a **fresh** connect or login flow (old authorization codes are single-use).

### No refresh token returned

Revoke Maya app access at [Google Account permissions](https://myaccount.google.com/permissions), then reconnect with `prompt=consent` (connect flow already requests this).

### OAuth tables missing (503)

```bash
cd packages/maya-db && DATABASE_URL=... python -m alembic upgrade head
```
