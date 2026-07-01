# YouTube OAuth (optional — homepage alerts use Atom feeds)

Hyprstart upload notifications for followed channels use **Atom feed polling**
(`maya-ingest poll`) and do **not** require YouTube OAuth.

OAuth is optional when you want to:

- Sync your full YouTube subscription list into the internal `youtube_*` tables
- Poll via YouTube Data API v3 (comments, enrichment, subscription-based discovery)

## Homepage path (recommended for MissKatie)

```bash
cd ~/Workspace-public
export DATABASE_URL=postgresql+asyncpg://maya:maya@localhost:5433/maya_public
make feeds-migrate
make gateway-dev          # restart if already running — needs DATABASE_URL
make seed-profiles
make ingest-poll
# enable scripts/systemd/maya-ingest-poll.timer for recurring polls
```

## Internal crawler OAuth (Workspace-internal)

1. Create a Google Cloud OAuth client (Web application).
2. Add redirect URI: `http://localhost:8001/api/v1/youtube/callback` (crawler default port).
3. Set environment on the crawler service:

   ```bash
   YOUTUBE_CLIENT_ID=...
   YOUTUBE_CLIENT_SECRET=...
   YOUTUBE_TOKEN_KEY=...   # Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Start crawler API; open `http://localhost:8001/api/v1/youtube/auth` and complete consent.
5. Celery beat runs `sync_all_youtube_subscriptions` daily and `poll_all_youtube_channels` hourly.

OAuth complements but does not replace the hyprstart notification path — bridge new
`youtube_videos` rows into `maya_public` notifications only if you build that integration later.
