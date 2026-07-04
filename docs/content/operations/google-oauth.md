---
title: Google OAuth
tags: [operations, oauth, google]
source: app-integrations-google-oauth.md
---

# Google OAuth

Google integration is optional but unlocks **Sign in with Google** on the login page and **Settings → Integrations** for Gmail inbox and Calendar reads. This guide covers Console setup, environment variables, and troubleshooting for both flows. Service-layer module breakdown lives in [[Services/Google Integrations]]; database tables are defined in [[Packages/Maya DB]].

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

Print the live checklist:

```bash
python scripts/verify_google_oauth.py
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

## Permission groups

| Permission | Google scopes |
|------------|---------------|
| `mailbox_read` | `gmail.readonly` |
| `mailbox_send` | `gmail.compose`, `gmail.send`, `gmail.modify` |
| `calendar_read` | `calendar.readonly` |
| `calendar_write` | `calendar` |

## Service APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /api/integrations/google/status` | Connection state |
| `GET /api/integrations/google/connect` | Start connect OAuth |
| `DELETE /api/integrations/google` | Disconnect |
| `GET /api/services/email/inboxes` | Inbox threads |
| `GET /api/services/calendar/events` | Calendar events |

## Troubleshooting

### redirect_uri_mismatch

Run `python scripts/verify_google_oauth.py` and match `Live redirect_uri` to Google Console exactly.

### Invalid code verifier

Start a fresh OAuth flow — authorization codes are single-use.

### OAuth tables missing (503)

Run Alembic migrations in `packages/maya-db`.

