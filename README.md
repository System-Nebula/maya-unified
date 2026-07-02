# Maya Unified

Local voice AI with a web dashboard: mic → Whisper → LLM → Qwen3-TTS, plus Discord tools, memory, and optional platform APIs (arena, discover, research).

**One repo. One clone. One venv. One launcher.**

```
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
setup_windows.bat    # or see NixOS below
launch.bat           # → http://localhost:8090
```

---

## What’s inside

This is not a launcher for external projects — voice and platform code live **in this repository**:

```
maya-unified/
├── packages/
│   ├── voice-runtime/      # STT, TTS, agent, Discord, memory, tools
│   ├── maya-contracts/     # shared API types
│   ├── maya-db/            # platform persistence
│   └── …                   # feeds, research, image, arena, …
├── apps/
│   ├── gateway/            # unified FastAPI entry (launch.py)
│   ├── dashboard/          # web UI
│   ├── maya-gateway/       # platform + voice SDK routes
│   ├── maya-bot/           # full Discord /imagine bot (optional)
│   └── maya-ingest/        # feed ingest worker (optional)
├── services/               # settings, hub, runtime patches
├── examples/               # bundled voice clip, personalities, starter skills
├── data/                   # your settings, memory, personalities (gitignored)
├── launch.py
├── setup_windows.bat
└── pyproject.toml          # single dependency manifest
```

Runtime state is always under `data/` at the repo root.

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| Python 3.11–3.12 | 3.13+ not supported |
| NVIDIA GPU | Strongly recommended |
| FFmpeg | Discord / YouTube playback |
| LM Studio | OpenAI-compatible API on `:1234` |

---

## Windows

```powershell
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
setup_windows.bat
copy .env.example .env
winget install Gyan.FFmpeg
launch.bat
```

`setup_windows.bat` creates `.venv` at the **repo root**, installs PyTorch (CUDA 12.8 wheels), and `pip install -e .`.

Start LM Studio, set your model id in **Settings → Reasoning**, open http://localhost:8090 .

### Bundled examples (first launch)

On first start, Maya copies shipped assets from `examples/` into your local runtime:

| Asset | Source | Destination |
|-------|--------|-------------|
| Demo voice clip | `examples/voices/ref.wav` + `ref.txt` | `packages/voice-runtime/voices/` |
| Personalities | `examples/personalities/personalities.json` | `data/personalities.json` |
| Starter skills | `examples/skills/*.md` | `data/skills/` |

Default personalities: **Maya-sama**, **Professor Mari**, **Call Center Scammer**. Tools (Discord, web, memory, MCP) ship as code in `packages/voice-runtime/tools/` — enable them in **Settings**.

<details>
<summary>Manual install</summary>

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install "torch>=2.7.0" torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[mcp,otel]"
```
</details>

---

## NixOS

```bash
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
nix develop
python -m venv .venv && source .venv/bin/activate
pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
pip install -e .
cp .env.example .env
./launch.sh
```

Enable NVIDIA + `allowUnfree` in `configuration.nix`. Stay inside `nix develop` for PortAudio/FFmpeg.

Optional full platform stack: `uv sync` from repo root (uses workspace in `pyproject.toml`).

---

## Web UI

| URL | Purpose |
|-----|---------|
| `/` | Dashboard — EQ, chat, tools |
| `/memory` | Memory explorer |
| `/settings` | Operator account + server voice config — open from the **user menu** (user chip → Settings) |
| `/login` | Operator sign-in |
| `/setup` | First-run admin creation (optional; demo admin auto-seeds on startup) |
| `/profile` | Redirects to `/settings?tab=account` (Account tab is the default on `/settings`) |
| `/admin/users` | Operator management (admin only) |
| `/docs` | OpenAPI |

---

## Operator auth

The unified dashboard uses **local operator accounts** (`operator_users` table) — separate from platform users (invite codes, OAuth, email) when the full maya-gateway stack is enabled.

| What | Where |
|------|-------|
| Operator credentials + roles | PostgreSQL (`operator_users`) |
| Sessions | Signed cookie `maya_op_session` (`SESSION_SECRET`) |
| User preferences | Browser `localStorage` (not synced to server) |

**Default account:** `admin` / `admin` — auto-created on startup when no operators exist. Change the password in the user menu → **Settings** (Account tab) after first sign-in.

**Sign in:** visit `/login` (or `/` → redirect).

**Roles:** `admin` (manage operators) and `operator` (dashboard access only).

Set in `.env`:

```env
SESSION_SECRET=change-me-in-production
SESSION_COOKIE_SECURE=0   # set 1 behind HTTPS
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public
OPERATOR_DEFAULT_USERNAME=admin
OPERATOR_DEFAULT_PASSWORD=admin
```

Run migrations before first login:

```bash
cd packages/maya-db && DATABASE_URL=... uv run alembic upgrade head
```

Protected APIs (`/api/voice/agent/*`, `/api/voice/settings/*`, `/api/operators/*`) return **401** without a valid operator session.

### Google OAuth

Optional **Sign in with Google** on `/login` and **Settings → Integrations** for Gmail/Calendar connect. Requires `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env`, Postgres migrations, and redirect URIs registered in Google Cloud Console.

See [app-integrations-google-oauth.md](app-integrations-google-oauth.md) for setup, Console checklist, and troubleshooting.

---

## Optional services

| Feature | How |
|---------|-----|
| Discord voice/music | Settings → Discord → bot token |
| Platform arena/discover | `uv sync` + Postgres (`DATABASE_URL` in `.env`) |
| `/imagine` Discord bot | `uv run maya-bot` from `apps/maya-bot` |
| Legacy voice WebUI | `python packages/voice-runtime/server.py` → `:7861` |

---

## Development

- **Unified changes** → `apps/`, `services/`
- **Voice engine** → `packages/voice-runtime/`
- **Platform** → `packages/maya-*`, `apps/maya-gateway/`

```bash
pip install -e .
python launch.py
```

---

## Data migration

If you previously ran voice-runtime with its own `data/` folder, the first unified start copies it into `data/` once (marker: `data/.migrated-from-qwen3`).

Voice reference clips go in `packages/voice-runtime/voices/` (or set path in Settings).
