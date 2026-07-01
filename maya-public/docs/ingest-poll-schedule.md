# Ingest poll schedule (homepage upload alerts)

Hyprstart upload notifications depend on `maya-ingest poll` running periodically.
The gateway and homepage UI only **display** alerts; ingest discovers new Atom feed entries.

## Prerequisites

- Postgres `maya_public` on `localhost:5433` (see root `Makefile` `PGPORT`)
- `make feeds-migrate` applied
- Gateway on `http://localhost:8090` (for bootstrap + SSE; poll itself only needs DB)
- Example follow graph seeded via `make seed-profiles` (see `operator_profiles_example.json`)

## One-shot poll

```bash
cd ~/Workspace-public
make ingest-poll
```

`ingest-poll` sets `DATABASE_URL` from Makefile `PG*` variables (default `maya:maya@localhost:5433/maya_public`).
Override if your credentials differ:

```bash
make ingest-poll PGUSER=maya PGPASSWORD=maya PGDATABASE=maya_public
```

## Gateway systemd user service

Hyprstart needs the gateway running with `DATABASE_URL` set (not the default `postgres@5432`).

```bash
mkdir -p ~/.config/systemd/user
cp scripts/systemd/maya-gateway.service ~/.config/systemd/user/
# Edit WorkingDirectory if not ~/Workspace-public
systemctl --user daemon-reload
systemctl --user enable --now maya-gateway.service
```

## Health check

```bash
make check-upload-alerts
make check-upload-alerts SKIP_GATEWAY=1   # DB only
```

## systemd user timer (recommended)

```bash
mkdir -p ~/.config/systemd/user
cp scripts/systemd/maya-ingest-poll.service ~/.config/systemd/user/
cp scripts/systemd/maya-ingest-poll.timer ~/.config/systemd/user/
# Edit WorkingDirectory / DATABASE_URL in the .service if not ~/Workspace-public
systemctl --user daemon-reload
systemctl --user enable --now maya-ingest-poll.timer
systemctl --user list-timers maya-ingest-poll.timer
```

Poll interval defaults to **20 minutes**. Edit `OnUnitActiveSec` in the timer unit to change it.

## cron alternative

```cron
*/20 * * * * cd $HOME/Workspace-public && make ingest-poll >>$HOME/.local/log/maya-ingest-poll.log 2>&1
```

## First poll after subscribe

The first poll for a channel is a **silent seed** (no notification flood). Only videos
published after that seed run trigger `new_video` inbox rows and the waybar bell.
