---
title: Operator Dashboard
tags: [apps, dashboard]
---

# Operator Dashboard

Static web UI in `apps/dashboard/` served by the unified gateway.

## Routes

| URL | Purpose |
|-----|---------|
| `/` | Main dashboard — EQ, chat, push-to-talk |
| `/memory` | Memory explorer |
| `/settings` | Account + voice configuration |
| `/login` | Operator sign-in |
| `/setup` | First-run admin creation |
| `/admin/users` | Operator management (admin role) |

User menu → **Settings** for account, reasoning provider, Discord, integrations.

Frontend modules include `apps/dashboard/js/mayaIntegrations.js` for Google connect UI.

